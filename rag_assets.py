"""Optional bounded image/OCR enrichment outside the browser request lifecycle."""
import hashlib
import copy
import os
import ipaddress
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

import requests

import article_store
import mineru_client
from image_assets import image_extension
from storage import read, save

ACTIVE = set()
GUARD = threading.Lock()
MAX_BYTES = 100 * 1024 * 1024


def reusable_images(batch_id, folder):
    """Find existing local assets for this author without downloading or OCR."""
    import author_batch
    from author_archive import author_key
    source = author_batch.load(batch_id)['source']
    found = {}
    for meta in folder.parent.glob('*/author-batch.json'):
        other = read(meta, {})
        if not other.get('source') or author_key(other['source']) != author_key(source):
            continue
        for page in article_store.result(meta.parent)['pages']:
            for item in page.get('images', []):
                path = (meta.parent / item.get('file', '')).resolve()
                if path.parent != (meta.parent / 'images').resolve() or not path.is_file():
                    continue
                previous = found.get(item['url'])
                if previous is None or (item.get('ocr') and not item.get('error')):
                    found[item['url']] = (path, copy.deepcopy(item))
    return found


def status(folder):
    result = read(folder / 'enrichment.json', {'state': 'idle'})
    if result['state'] == 'running' and str(folder) not in ACTIVE:
        result = {**result, 'state': 'interrupted', 'message': '服务重启中断了图片处理，可点击重试。'}
    return {**result, 'ocr_available': mineru_client.available(), 'ocr_provider': 'MinerU VLM'}


def validate_image_url(url):
    u = urlsplit(url)
    if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
        raise ValueError('图片仅支持公共 HTTPS 地址')
    addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('不下载本机或内网图片')
    return url


def download(url, target, budget):
    validate_image_url(url)
    deadline = time.monotonic() + 20
    # No browser cookies, environment credentials or redirect chains.
    with requests.Session() as client:
        client.trust_env = False
        with client.get(url, timeout=(5, 8), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError('图片 HTTP ' + str(response.status_code))
            body = bytearray()
            for part in response.iter_content(65536):
                body.extend(part)
                if len(body) > min(8 * 1024 * 1024, budget) or time.monotonic() > deadline:
                    raise ValueError('图片超过大小或时间上限')
    path = target / (hashlib.sha256(body).hexdigest() + image_extension(body))
    if not path.exists():
        path.write_bytes(body)
    return path


def ocr_engine():
    engine = shutil.which('tesseract')
    if not engine:
        raise ValueError('未安装 Tesseract OCR；图片下载可单独使用。OCR 需要 Tesseract 及 chi_sim、eng 语言包。')
    result = subprocess.run([engine, '--list-langs'], capture_output=True, timeout=15,
                            encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    languages = set(result.stdout.split())
    if result.returncode or not {'chi_sim', 'eng'} <= languages:
        raise ValueError('OCR 缺少 chi_sim 或 eng 语言包')
    return engine


def start(batch_id, ocr=False, pipeline=False):
    import author_batch
    folder = author_batch.job_folder(batch_id)
    engine = 'mineru' if ocr else None
    if ocr:
        mineru_client.token()
    with GUARD, author_batch.LOCK:
        batch = author_batch.load(batch_id)
        if not pipeline and batch.get('auto_state') in ('queued', 'recognizing', 'saving'):
            raise ValueError('自动识别与保存正在进行，请等待完成')
        if batch['state'] == 'running':
            raise ValueError('请先暂停采集或等待本轮结束，再处理图片')
        if str(folder) in ACTIVE:
            return status(folder)
        if ACTIVE:
            raise ValueError('已有图片任务进行中，请等待完成')
        if not article_store.count(folder):
            raise ValueError('尚无已保存文章')
        ACTIVE.add(str(folder))
        save(folder / 'enrichment.json', {'state': 'running', 'done': 0, 'message': '正在下载正文图片', 'ocr': ocr})
        threading.Thread(target=run, args=(batch_id, folder, engine), daemon=True).start()
    return status(folder)


def run(batch_id, folder, engine, selected_pages=None):
    import author_batch
    done = failed = 0
    try:
        target = folder / 'images'
        target.mkdir(exist_ok=True)
        budget = MAX_BYTES - sum(p.stat().st_size for p in target.iterdir() if p.is_file())
        deadline = time.monotonic() + 1800
        pages = article_store.result(folder)['pages'] if selected_pages is None else selected_pages
        # Windows cannot atomically replace a metadata file while another
        # thread has it open. Share the queue lock for this local snapshot.
        with author_batch.LOCK:
            reusable = reusable_images(batch_id, folder)
        for page in pages:
            pending=[]
            for index, item in enumerate(page.get('images', [])):
                try:
                    item.pop('error', None)
                    if index >= 40 or time.monotonic() >= deadline:
                        raise ValueError('达到每篇 40 张或本次 30 分钟处理上限')
                    path = (folder / item.get('file', '')).resolve()
                    if path.parent != target.resolve() or not path.is_file():
                        if budget <= 0:
                            raise ValueError('达到每任务 100 MB 图片上限')
                        cached = reusable.get(item['url'])
                        if cached and cached[0].is_file():
                            cached_path, cached_item = cached
                            size = cached_path.stat().st_size
                            if size > budget:
                                raise ValueError('达到每任务 100 MB 图片上限')
                            digest = hashlib.sha256(cached_path.read_bytes()).hexdigest()
                            path = target / (digest + cached_path.suffix)
                            if not path.exists():
                                shutil.copyfile(cached_path, path)
                            if cached_item.get('ocr', {}).get('image_sha256') == digest:
                                item['ocr'] = copy.deepcopy(cached_item['ocr'])
                        else:
                            path = download(item['url'], target, budget)
                        budget -= path.stat().st_size
                        item['file'] = 'images/' + path.name
                    item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                    if engine == 'mineru' and (item.get('ocr', {}).get('engine') != 'mineru' or item.get('ocr', {}).get('image_sha256') != item['sha256']):
                        save(folder / 'enrichment.json', {'state': 'running', 'done': done, 'total': len(pages),
                            'message': f'MinerU 正在识别第 {done + 1} 篇的第 {index + 1} 张图片，可离开页面等待。'})
                        if os.environ.get('MINERU_MODE')=='hybrid':
                            from mineru_dispatch import submit
                            pending.append((item,path,submit(path)))
                        else:
                            item['ocr'] = mineru_client.recognize(path)
                    elif engine and engine != 'mineru' and not item.get('ocr'):
                        result = subprocess.run([engine, str(path), 'stdout', '-l', 'chi_sim+eng'],
                            capture_output=True, timeout=30, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        if result.returncode:
                            raise ValueError('OCR 识别失败')
                        item['ocr'] = {'text': result.stdout.strip(), 'engine': 'tesseract',
                                       'language': 'chi_sim+eng', 'verified': False}
                    reusable[item['url']] = (path, copy.deepcopy(item))
                except Exception as exc:
                    item['error'] = str(exc)[:200]
                    failed += 1
            for item,path,future in pending:
                try:
                    item['ocr']=future.result()
                    reusable[item['url']] = (path, copy.deepcopy(item))
                except Exception as exc:
                    item['error']=str(exc)[:200]
                    failed+=1
            with author_batch.LOCK:
                article_store.put(folder, page, replace=True)
                if selected_pages is None:
                    batch = author_batch.load(batch_id)
                    batch['revision'] += 1
                    author_batch.persist(batch)
            done += 1
            save(folder / 'enrichment.json', {'state': 'running', 'done': done, 'total': len(pages), 'failed_images': failed})
        save(folder / 'enrichment.json', {'state': 'finished', 'done': done, 'failed_images': failed,
             'message': f'图片处理结束，{failed} 张图片未完成下载或 OCR；请重新保存资料包。'})
    except Exception as exc:
        save(folder / 'enrichment.json', {'state': 'failed', 'done': done, 'message': str(exc)[:200]})
    finally:
        with GUARD:
            ACTIVE.discard(str(folder))
