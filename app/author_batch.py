"""Durable author queues. The browser supplies rendered pages; no remote fetch here."""
import io
import hashlib
import json
import re
import threading
import time
import uuid
import zipfile
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from content import classify, page_record
import article_store
import rag_assets
from article_metadata import extract_metadata, extract_account_name
from export_names import export_name
from jobs import job_folder
from storage import DATA, read, save

LOCK = threading.RLock()


def scan_mode(config):
    mode = config.get('scan_mode', 'incremental')
    if mode not in ('incremental', 'history'):
        raise ValueError('采集模式应为快速增量更新或补齐历史')
    return mode


def failed_article(data, reason, deleted=False):
    """Retry once, then record a failure without marking it as saved."""
    url=data['urls'][data['cursor']]
    attempt=data.get('article_retry',0)
    if not deleted and attempt < 1:
        data.update(article_retry=1, message='当前文章失败，自动重试一次：'+reason)
    else:
        article_store.fail(job_folder(data['id']), {'url':url, 'reason':reason,
            'kind':'deleted' if deleted else 'failed_after_retry', 'attempts':attempt+1})
        data.update(cursor=data['cursor']+1, article_retry=0,
                    consecutive_failures=0 if deleted else data.get('consecutive_failures',0)+1,
                    message='当前文章不可用，已记录并继续下一篇：'+reason)
        if data['cursor'] >= len(data['urls']):
            data.update(state='finished',message='本轮处理结束，失败文章已记录，已有正文保留。')
        elif not deleted and data['consecutive_failures'] >= 3:
            data.update(state='needs_user',message='连续 3 篇文章失败，已暂停检查登录或站点状态，避免批量误跳过。')
    data['revision'] += 1
    data['not_before']=time.time()+3
    return persist(data)


def deleted_page(markup):
    soup=BeautifulSoup(markup,'html.parser')
    for node in soup.select('script,style,noscript,aside,nav,footer,[hidden],[aria-hidden="true"]'):
        node.decompose()
    text=soup.get_text(' ',strip=True)
    article=soup.select_one('#js_content, .article__bd, .status-content, .article-content')
    return not (article and len(article.get_text(strip=True))>80) and len(text)<1500 and bool(re.search(
        r'(?:该|此|这篇)(?:文章|内容|帖子|讨论|页面).{0,8}(?:已被删除|已删除|不存在)|原文已删除|内容已被发布者删除|你访问的页面不存在|您访问的页面不存在',text))


def incremental_boundary(data, links, scan):
    """Count only newly observed URLs, never repeated polling of one screen."""
    if data.get('scan_mode', 'history') != 'incremental' or scan.get('loading'):
        return False
    seen = set(data.get('scan_seen', []))
    current = {u for link in links if (u := article_url(link, data['source']))}
    fresh = current - seen
    if not fresh:
        return False
    data['scan_seen'] = sorted(seen | current)
    saved = set(data.get('known_saved', []))
    if fresh <= saved:
        data['old_batches'] = data.get('old_batches', 0) + 1
        data['old_links'] = data.get('old_links', 0) + len(fresh)
    else:
        data['old_batches'] = data['old_links'] = 0
    return data['old_batches'] >= 3 and data['old_links'] >= 30


def source_info(value):
    value = str(value).strip()
    u = urlsplit(value)
    if u.scheme != 'https' or u.username or u.password or u.port:
        raise ValueError('请粘贴完整的 HTTPS 作者主页网址，不能只填作者名称')
    if u.hostname in ('xueqiu.com', 'www.xueqiu.com'):
        match = re.fullmatch(r'/(?:u/)?(\d+)/?', u.path)
        if not match:
            raise ValueError('雪球请填写作者主页，例如 https://xueqiu.com/u/1234567890')
        return {'platform': 'xueqiu', 'owner': match[1], 'url': 'https://' + u.hostname + '/u/' + match[1]}
    if u.hostname == 'mp.weixin.qq.com' and (
        u.path in ('/mp/profile_ext', '/mp/appmsgalbum', '/s') or u.path.startswith('/s/')
    ):
        return {'platform': 'wechat', 'owner': parse_qs(u.query).get('__biz', [''])[0],
                'url': urlunsplit((u.scheme, u.netloc, u.path, u.query, ''))}
    raise ValueError('仅支持雪球作者主页、微信公众号历史列表／合集或文章网址')


def article_url(value, source):
    try:
        u = urlsplit(str(value))
        if u.scheme != 'https' or u.username or u.password or u.port:
            return None
        if source['platform'] == 'xueqiu':
            if u.hostname in ('xueqiu.com', 'www.xueqiu.com') and re.fullmatch('/' + source['owner'] + r'/\d+/?', u.path):
                return 'https://' + urlsplit(source['url']).hostname + u.path.rstrip('/')
        elif u.hostname == 'mp.weixin.qq.com':
            if re.fullmatch(r'/s/[\w-]+', u.path):
                return 'https://mp.weixin.qq.com' + u.path
            if u.path == '/s':
                query = parse_qs(u.query)
                if not all(query.get(k) for k in ('__biz', 'mid', 'idx', 'sn')):
                    return None
                if source['owner'] and query['__biz'][0] != source['owner']:
                    return None
                return 'https://mp.weixin.qq.com/s?' + urlencode({k: query[k][0] for k in ('__biz', 'mid', 'idx', 'sn')})
    except ValueError:
        pass
    return None


def load(batch_id):
    data = read(job_folder(batch_id) / 'author-batch.json')
    if not data:
        raise ValueError('作者任务不存在')
    return data


def previously_saved(source, batch_id):
    found = set()
    for path in job_folder(batch_id).parent.glob('*/author-batch.json'):
        if path.parent.name == batch_id:
            continue
        old = read(path, {})
        if old.get('source', {}).get('platform') == source['platform']:
            found.update(normalized for url in article_store.urls(path.parent) if (normalized := article_url(url, source)))
    return found


def persist(data):
    folder = job_folder(data['id'])
    save(folder / 'author-batch.json', data)
    saved_count = article_store.count(folder)
    save(folder / 'status.json', {'id': data['id'], 'url': data['source']['url'],
        'created': data['created'], 'status': 'cancelled' if data['state']=='cancelled' else 'done' if data['state'] == 'finished' else 'needs_user',
        'pages': saved_count, 'rows': saved_count, 'source': 'author-batch'})
    if data['state'] == 'finished' and data.get('auto_after') and data.get('auto_state') in (None, 'streaming') and saved_count:
        import author_pipeline
        author_pipeline.enqueue(data)
    return public(data)


def public(data):
    saved_count = article_store.count(job_folder(data['id']))
    index = data['cursor']
    return {**{k: data[k] for k in ('id', 'source', 'created', 'state', 'phase', 'revision', 'limit', 'message')},
        'skipped_existing': len(data.get('skipped_urls', [])), 'discovered': len(data['urls']), 'saved': saved_count, 'processed': index,
        'url': data['source']['url'] if data['phase'] == 'scan' else (data['urls'][index] if index < len(data['urls']) else ''),
        'not_before': data['not_before'], 'last_export': data.get('last_export'),
        'output_mode': data.get('output_settings', {}).get('mode'), 'discovery_reason': data.get('discovery_reason'),
        'scan_mode': data.get('scan_mode', 'history'), 'history_complete': data.get('history_complete', False),
        'article_retry': data.get('article_retry',0),
        'article_retry_supported': True,
        'auto_after': data.get('auto_after', False), 'auto_state': data.get('auto_state'), 'auto_message': data.get('auto_message', ''),
        'enrichment': rag_assets.status(job_folder(data['id']))}


def create(config):
    mode = scan_mode(config)
    source = source_info(config.get('url', ''))
    limit = int(config.get('limit', 500))
    if not 1 <= limit <= 5000:
        raise ValueError('每个作者上限应为 1–5000 篇')
    batch_id = str(uuid.uuid4())
    job_folder(batch_id).mkdir()
    seed = article_url(source['url'], source)
    from download_settings import settings
    data = {'auto_after': config.get('auto_after') is True, 'output_settings': settings(), 'id': batch_id, 'source': source, 'state': 'paused', 'phase': 'capture' if seed else 'scan',
        'urls': [seed] if seed else [], 'cursor': 0, 'revision': 0, 'limit': limit,
        'stagnant': 0, 'rounds': 0, 'not_before': 0, 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        'message': '已创建，点击继续开始。' + ('单篇微信文章只保存该篇；批量历史请提供历史列表或合集网址。' if seed else '')}
    data.update(scan_mode=mode, history_complete=False)
    data['known_saved'] = sorted(previously_saved(source, batch_id))
    data['skipped_urls'] = []
    if seed and seed in data['known_saved']:
        data.update(urls=[], skipped_urls=[seed], state='finished', message='此文章已成功保存，跳过重复下载。')
    return persist(data)


def control(batch_id, action):
    with LOCK:
        data = load(batch_id)
        import author_pipeline
        if batch_id in author_pipeline.PENDING:
            raise ValueError('自动识别与保存正在收尾，请稍后再操作')
        if data.get('auto_state') in ('queued', 'recognizing', 'saving') or (str(job_folder(batch_id)) in rag_assets.ACTIVE and data.get('auto_state') != 'streaming'):
            raise ValueError('图片正在处理，请等待完成后继续采集')
        if action not in ('pause', 'resume', 'finish-scan', 'skip', 'rescan', 'retry-output', 'cancel'):
            raise ValueError('不支持的操作')
        if action == 'cancel':
            if data['state'] != 'cancelled':
                data.update(state='cancelled', auto_after=False, auto_state=None,
                            auto_message='任务已取消；已开始的图片处理可完成，未开始的队列不再执行。',
                            message='任务已取消，已采集正文、图片和查重记录全部保留。')
                data['revision'] += 1
                if article_store.count(job_folder(batch_id)) and data.get('output_settings', {}).get('mode')=='folder':
                    author_pipeline.enqueue_cancelled(data)
            return persist(data)
        if data['state'] == 'cancelled':
            raise ValueError('任务已取消，请新建任务；已有正文会自动查重跳过')
        if action in ('rescan', 'retry-output'):
            from download_settings import settings
            data.update(auto_after=True, output_settings=settings(), auto_state=None)
            if action == 'rescan':
                data.update(phase='scan', scan_mode='history', history_complete=False, scan_seen=[], old_batches=0, old_links=0, stagnant=0, rounds=0, end_rounds=0, discovery_reason=None, known_saved=sorted(previously_saved(data['source'], batch_id)))
        if action == 'resume' and data['phase'] == 'scan':
            data.update(stagnant=0, rounds=0, end_rounds=0)
        if action == 'skip':
            if data['phase'] != 'capture' or data['cursor'] >= len(data['urls']):
                raise ValueError('当前没有可以跳过的文章')
            article_store.fail(job_folder(batch_id), {'url': data['urls'][data['cursor']], 'reason': '用户跳过：' + data['message']})
            data['cursor'] += 1
            data.update(article_retry=0,consecutive_failures=0)
        if action == 'finish-scan':
            if data['phase'] != 'scan':
                raise ValueError('当前不在发现列表阶段')
            data['phase'] = 'capture'
            data['discovery_reason'] = '手动停止发现'
        data['state'] = 'paused' if action == 'pause' else 'running'
        data['revision'] += 1
        data['message'] = '已暂停，可继续。' if action == 'pause' else '正在处理浏览器可访问的内容。'
        if data['phase'] == 'capture' and data['cursor'] >= len(data['urls']):
            data['state'] = 'finished'
            data['message'] = '本轮结束；仅包含已发现的链接，不代表作者的全部历史。'
        return persist(data)


def report(batch_id, payload):
    with LOCK:
        data = load(batch_id)
        if data['state'] != 'running' or payload.get('revision') != data['revision']:
            return public(data)  # A paused, duplicate or obsolete browser reply cannot advance the queue.
        if time.time() < data['not_before']:
            return public(data)
        markup = payload.get('html', '')
        if not isinstance(markup, str) or not markup.strip():
            raise ValueError('页面尚未加载出内容')
        account_name = extract_account_name(markup, data['source'])
        if account_name:
            data['source']['name'] = account_name
        current = public(data)['url']
        observed = str(payload.get('url', ''))
        if data['phase'] == 'scan':
            actual = source_info(observed)
            if actual['platform'] != data['source']['platform'] or actual['owner'] != data['source']['owner']:
                raise ValueError('浏览器已离开指定作者列表，请回到原作者页面')
        reason = classify(markup)
        if data['phase']=='capture':
            observed_path=urlsplit(observed).path.lower()
            gated=reason in ('login','verification','blocked','rate_limited') or bool(re.search(r'/(?:login|signin|captcha|verify|account/login)(?:/|$)',observed_path))
            if not gated:
                if deleted_page(markup):
                    return failed_article(data,'页面明确提示文章已删除或不存在',deleted=True)
                if article_url(observed,data['source']) != current:
                    return failed_article(data,'文章跳转到其他页面（未判定为删除）：'+observed[:300])
                if reason not in ('ok','paywall'):
                    return failed_article(data,'页面加载失败：'+reason)
            else:
                data.update(state='needs_user',message='页面需要登录、验证或访问受限，请处理后继续；未跳过当前文章。')
                data['revision']+=1
                return persist(data)
        if reason not in ('ok', 'paywall'):
            data.update(state='needs_user', message='页面需要登录、验证或尚未加载完成：' + reason + '。请在扩展打开的标签页处理后点击继续。')
        elif data['phase'] == 'scan':
            links = payload.get('links', [])
            if not isinstance(links, list) or len(links) > 10000:
                raise ValueError('列表链接数量异常')
            before = len(data['urls'])
            known = set(data['urls'])
            saved = set(data.get('known_saved', []))
            skipped = set(data.get('skipped_urls', []))
            skipped_before = len(skipped)
            for link in links:
                candidate = article_url(link, data['source'])
                if candidate in saved and candidate not in known:
                    skipped.add(candidate)
                    continue
                if candidate and candidate not in known and len(data['urls']) < data['limit']:
                    data['urls'].append(candidate)
                    known.add(candidate)
            data['skipped_urls'] = sorted(skipped)
            data['stagnant'] = data['stagnant'] + 1 if before == len(data['urls']) and len(skipped) == skipped_before else 0
            data['rounds'] += 1
            scan = payload.get('scan') or {}
            if not isinstance(scan, dict):
                raise ValueError('列表进度格式不正确')
            if scan.get('progress') or scan.get('loading'):
                data['stagnant'] = 0
            data['end_rounds'] = data.get('end_rounds', 0) + 1 if scan.get('explicit_end') and not scan.get('loading') else 0
            boundary = incremental_boundary(data, links, scan)
            data['message'] = f'已发现 {len(data["urls"])} 篇，继续翻页／加载历史。'
            if len(data['urls']) >= data['limit'] or data['end_rounds'] >= 2 or boundary:
                data['phase'] = 'capture'
                data['history_complete'] = data['end_rounds'] >= 2 and len(data['urls']) < data['limit']
                data['discovery_reason'] = ('达到设置上限' if len(data['urls']) >= data['limit'] else
                    '页面明确显示末尾' if data['end_rounds'] >= 2 else '快速增量：连续 3 批至少 30 篇均已入库，停止向历史翻页')
                data['message'] = '发现结束，开始保存新增正文。' if data['urls'] else '本次扫描范围内没有未入库文章；未检查更早历史。'
            elif data['stagnant'] >= 30 or data['rounds'] >= 2000:
                data.update(state='needs_user', message='列表长时间未加载出新内容，尚未确认到达末尾。请检查采集标签页后继续，或选择停止发现并保存已找到文章。')
        else:
            if current in previously_saved(data['source'], batch_id):
                data['skipped_urls'] = sorted(set(data.get('skipped_urls', [])) | {current})
                data['cursor'] += 1
                if data['cursor'] >= len(data['urls']):
                    data['state'] = 'finished'
                data['revision'] += 1
                data['message'] = '该文章已在其他任务成功保存，已跳过重复下载。'
                return persist(data)
            try:
                record = page_record(current, markup, 'extension-author-batch')
                if not record['text'].strip():
                    raise ValueError('未找到正文')
            except ValueError as exc:
                return failed_article(data,str(exc))
            else:
                record['notes'].append('作者批量采集：仅保存浏览器可见正文，图片保留原链接。')
                record['captured_at'] = datetime.now(timezone.utc).isoformat()
                record.update(extract_metadata(markup))
                article_store.put(job_folder(batch_id), record)
                data.update(article_retry=0,consecutive_failures=0)
                if data.get('auto_after'):
                    import author_pipeline
                    data.update(auto_state='streaming', auto_message='正文持续采集中，已保存文章的图片正在后台排队识别。')
                    author_pipeline.enqueue_article(batch_id, current)
                data['cursor'] += 1
                data['message'] = f'已保存 {article_store.count(job_folder(batch_id))} 篇。'
        if data['phase'] == 'capture' and data['cursor'] >= len(data['urls']):
            data.update(state='finished', message='本轮结束。仅包含已发现且可访问的文章，不代表全部历史。' + f" 已跳过 {len(data.get('skipped_urls', []))} 篇已保存文章。")
        data['revision'] += 1
        data['not_before'] = time.time() + 3
        return persist(data)


def bundle(batch_id):
    data = load(batch_id)
    if str(job_folder(batch_id)) in rag_assets.ACTIVE:
        raise ValueError('图片正在处理，请等待完成后导出')
    result = article_store.result(job_folder(batch_id))
    output = io.BytesIO()
    documents = []
    added = set()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, page in enumerate(result['pages'], 1):
            images = []
            for item in page.get('images', []):
                item = dict(item)
                path = (job_folder(batch_id) / item.get('file', '')).resolve()
                if path.parent == (job_folder(batch_id) / 'images').resolve() and path.is_file():
                    if item['file'] not in added:
                        archive.write(path, item['file'])
                        added.add(item['file'])
                else:
                    item.pop('file', None)
                images.append(item)
            documents.append({
                'schema_version': 1,
                'document_id': hashlib.sha256(page['url'].encode('utf-8')).hexdigest(),
                'source_url': page['url'], 'platform': data['source']['platform'],
                'author_id': data['source']['owner'] or None, 'author_url': data['source']['url'],
                'author_name': page.get('author_name'), 'title': page['title'],
                'published_at': page.get('published_at'), 'published_at_raw': page.get('published_at_raw'), 'captured_at': page.get('captured_at'),
                'text': page['text'], 'markdown': page['markdown'],
                'content_hash': hashlib.sha256(re.sub(r'\s+', ' ', page['text']).strip().encode('utf-8')).hexdigest(),
                'partial_content': bool(page.get('partial_content')), 'extraction': page.get('extraction'),
                'images': images, 'metadata_source': page.get('metadata_source'),
                'retrieval_hash': hashlib.sha256(json.dumps({'text': page['text'], 'title': page['title'],
                    'author': page.get('author_name'), 'published_at': page.get('published_at'),
                    'partial_content': bool(page.get('partial_content')), 'images': images}, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                'notes': page.get('notes', []),
            })
            markdown = page['markdown']
            for item in images:
                if item.get('file'):
                    markdown = markdown.replace(item['url'], item['file'])
            for item in images:
                if item.get('ocr'):
                    markdown += '\n\n### 图片识别（机器识别，未经校验）\n\n来源图片：' + item['url'] + '\n\n' + (item['ocr'].get('markdown') or item['ocr'].get('text', ''))
            name = export_name({'pages': [page]}, data, batch_id, 'md')
            archive.writestr(f'{index:04d}_{name}', ('# ' + page['title'] + '\n\n来源：' + page['url'] +
                '\n\n说明：仅保存可见正文；已下载图片使用本地路径，其余保留原链接。\n\n' + markdown).encode('utf-8-sig'))
        archive.writestr('documents.jsonl', ''.join(json.dumps(doc, ensure_ascii=False) + '\n' for doc in documents).encode('utf-8'))
        archive.writestr('RAG导入说明.txt', 'documents.jsonl 使用 UTF-8，每行一篇完整文章。text 是正文，markdown 保留结构。\n'
            'document_id 按来源网址生成，可用于同一文章更新；content_hash 按规范化正文生成，可辅助去重。\n'
            'author_name、published_at 缺失时为 null；captured_at 为实际采集时间，旧记录可能为空，不能当作发布时间。\n'
            'partial_content 表示检测到的试读提示；false 不保证全文完整。images 中的 file 为本地图片路径，ocr 为可选机器识别文本，verified=false，不应当成原文。\n'
            'retrieval_hash 包含正文、元数据与图片 OCR；增量入库建议比较此值，content_hash 仅用于正文去重。\n'
            '请在 RAG 入库阶段按标题／段落切块，为块保留 document_id、source_url、作者和时间，再生成向量。\n')
        archive.writestr('采集清单.json', json.dumps({'source': data['source'], 'state': data['state'],
            'discovered': data['urls'], 'saved': [p['url'] for p in result['pages']],
            'remaining': data['urls'][data['cursor']:], 'failures': result.get('failures', []), 'message': data['message'],
            'completeness': '不保证作者全部历史；仅收集列表可发现且浏览器可访问的正文。'}, ensure_ascii=False, indent=2))
    return output.getvalue()


def save_to_folder(batch_id, output_settings=None):
    from author_archive import export_author
    with LOCK:
        return export_author(batch_id, output_settings)


def save_snapshot_to_folder(batch_id, output_settings=None):
    """Write an immutable, ready-marked directory for an Agent to ingest."""
    from download_settings import folder_path, settings
    with LOCK:
        data = load(batch_id)
        result = article_store.result(job_folder(batch_id))
        if not result['pages']:
            raise ValueError('尚无成功保存的正文')
        root = folder_path((output_settings or settings())['folder'])
        owner = re.sub(r'[^\w-]', '_', data['source']['owner'])[:48] or hashlib.sha256(data['source']['url'].encode()).hexdigest()[:12]
        parent = root / (data['source']['platform'] + '_' + owner)
        parent.mkdir(parents=True, exist_ok=True)
        stamp = re.sub(r'\D', '', data['created'])[:14]
        destination = parent / f'{stamp}_{batch_id[:8]}_r{data["revision"]}'
        with zipfile.ZipFile(io.BytesIO(bundle(batch_id))) as archive:
            digest = hashlib.sha256(archive.read('documents.jsonl')).hexdigest()
            file_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
            # An unchanged snapshot can be saved again without overwriting any user file.
            marker = read(destination / 'export.json', {})
            intact = marker.get('files_sha256') == file_hashes and all(
                (destination / name).is_file() and hashlib.sha256((destination / name).read_bytes()).hexdigest() == value
                for name, value in file_hashes.items())
            if marker.get('documents_sha256') == digest and marker.get('ready') is True and intact:
                export = {**marker, 'folder': str(destination), 'reused': True}
            else:
                if destination.exists():
                    destination = destination.with_name(destination.name + '_' + uuid.uuid4().hex[:8])
                destination.mkdir()
                for member in archive.infolist():
                    relative = PurePosixPath(member.filename)
                    if relative.is_absolute() or '..' in relative.parts or '\\' in member.filename or ':' in member.filename or (len(relative.parts) != 1 and (len(relative.parts) != 2 or relative.parts[0] != 'images')):
                        raise ValueError('导出文件名不正确')
                    (destination / member.filename).parent.mkdir(exist_ok=True)
                    with (destination / member.filename).open('xb') as output:
                        output.write(archive.read(member))
                export = {'schema_version': 1, 'batch_id': batch_id, 'revision': data['revision'],
                    'state': data['state'], 'documents_count': len(result['pages']),
                    'documents_sha256': digest, 'documents_file': str(destination / 'documents.jsonl'),
                    'documents_relative_path': 'documents.jsonl', 'files_sha256': file_hashes,
                    'exported_at': datetime.now(timezone.utc).isoformat(),
                    'folder': str(destination), 'reused': False, 'ready': True}
                # Agents should only ingest directories after this final marker appears.
                save(destination / 'export.json', export)
        data['last_export'] = export
        save(job_folder(batch_id) / 'author-batch.json', data)
        return export
