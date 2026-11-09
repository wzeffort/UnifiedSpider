"""Stable author archives. Only export files are changed; source jobs stay intact."""
import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone

from storage import read, save


def author_key(source):
    # A short WeChat article URL does not identify an account. Never combine
    # unrelated accounts just because their owner field is empty.
    owner = source.get('owner') or hashlib.sha256(source['url'].encode()).hexdigest()
    if source['platform'] == 'xueqiu':
        return 'xueqiu_' + owner
    return source['platform'] + '_' + hashlib.sha256(owner.encode()).hexdigest()[:24]


def canonical_url(url):
    return url.replace('https://www.xueqiu.com/', 'https://xueqiu.com/')


def write_changed(path, content, expected=None):
    """Atomic replacement, preserving any user-edited generated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = path.read_bytes()
        if old == content:
            return False
        if expected is None or hashlib.sha256(old).hexdigest() != expected:
            backup = path.parent / '_user_backups'
            backup.mkdir(exist_ok=True)
            (backup / (path.name + '.' + uuid.uuid4().hex)).write_bytes(old)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(content)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return True


def export_author(batch_id, output_settings=None):
    import author_batch as batch
    import article_store
    import rag_assets
    from download_settings import folder_path, settings

    data = batch.load(batch_id)
    folder = batch.job_folder(batch_id)
    count = article_store.count(folder)
    if not count:
        raise ValueError('尚无成功保存的正文')
    if str(folder) in rag_assets.ACTIVE:
        raise ValueError('图片正在处理，请等待完成后导出')
    from author_directory import resolve_directory
    archive_identity = author_key(data['source'])
    # Reuse verified account names learned in earlier capture tasks.
    if not data['source'].get('name'):
        for meta in folder.parent.glob('*/author-batch.json'):
            old = read(meta, {})
            if old.get('source', {}).get('name') and author_key(old['source']) == archive_identity:
                data['source']['name'] = old['source']['name']
                break
    destination = resolve_directory(folder_path((output_settings or settings())['folder']), data['source'], archive_identity)
    destination.mkdir(parents=True, exist_ok=True)
    marker = read(destination / 'export.json', {})
    previous_hashes = marker.get('files_sha256', {})
    # Load the prior committed index, including documents whose source jobs may
    # since have been removed. Invalid JSON fails before modifying any files.
    documents = {}
    index_path = destination / 'documents.jsonl'
    if index_path.exists():
        try:
            for line in index_path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    doc = json.loads(line)
                    documents[doc['document_id']] = doc
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError('作者 documents.jsonl 已被修改或损坏；请先备份并恢复该文件，原文件未覆盖') from exc

    files = {}
    histories = []
    for path in folder.parent.glob('*/author-batch.json'):
        old = read(path, {})
        if not old.get('source') or author_key(old['source']) != author_key(data['source']):
            continue
        if path.parent == folder:
            continue
        # A concurrently running author task will merge itself when it finishes.
        if old.get('state') == 'running' or str(path.parent) in rag_assets.ACTIVE:
            continue
        histories.append((old.get('created', ''), path.parent.name))
    histories.sort()
    ids = [key for _, key in histories] + [batch_id]
    for key in ids:
        with zipfile.ZipFile(io.BytesIO(batch.bundle(key))) as archive:
            docs = [json.loads(line) for line in archive.read('documents.jsonl').decode('utf-8').splitlines()]
            for doc in docs:
                doc['source_url'] = canonical_url(doc['source_url'])
                doc['author_url'] = canonical_url(doc['author_url'])
                doc['document_id'] = hashlib.sha256(doc['source_url'].encode()).hexdigest()
                identity = doc['document_id']
                previous = documents.get(identity)
                # Do not regress successful OCR when re-exporting older tasks.
                if previous and previous.get('content_hash') == doc.get('content_hash'):
                    old_images = {i['url']: i for i in previous.get('images', [])}
                    for image in doc.get('images', []):
                        old_image = old_images.get(image['url'], {})
                        if old_image.get('ocr') and not old_image.get('error') and (not image.get('ocr') or image.get('error')):
                            image['ocr'] = old_image['ocr']
                            image.pop('error', None)
                        if not image.get('file') and old_image.get('file') and (destination / old_image['file']).is_file():
                            image['file'] = old_image['file']
                for image in doc.get('images', []):
                    name = image.get('file')
                    if name and name in archive.namelist():
                        body = archive.read(name)
                        # Production downloads already use content hashes; this
                        # also prevents collisions in legacy imported filenames.
                        suffix = name.rsplit('.', 1)[-1]
                        if not re.fullmatch('[a-zA-Z0-9]{1,8}', suffix):
                            suffix = 'bin'
                        image['file'] = 'images/' + hashlib.sha256(body).hexdigest() + '.' + suffix
                        files[image['file']] = body
                markdown = doc['markdown']
                for image in doc.get('images', []):
                    if image.get('file'):
                        markdown = markdown.replace(image['url'], image['file'])
                    if image.get('ocr'):
                        markdown += '\n\n### 图片识别（机器识别，未经校验）\n\n来源图片：' + image['url'] + '\n\n' + (image['ocr'].get('markdown') or image['ocr'].get('text', ''))
                doc['markdown_file'] = identity + '.md'
                doc['retrieval_hash'] = hashlib.sha256(json.dumps({k: doc.get(k) for k in ('text', 'title', 'author_name', 'published_at', 'partial_content', 'images')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                documents[identity] = doc
                files[doc['markdown_file']] = ('# ' + doc['title'] + '\n\n来源：' + doc['source_url'] + '\n\n' + markdown).encode('utf-8-sig')
            files['RAG导入说明.txt'] = archive.read('RAG导入说明.txt') + '\n同一作者在此目录增量合并。仅导入本目录 documents.jsonl；不要递归导入旧时间戳目录或 _user_backups。export.json 的 ready=true 才代表本次导出完成；读取前后请核对 generation 未变化。\n'.encode('utf-8')
    files['documents.jsonl'] = ''.join(json.dumps(documents[key], ensure_ascii=False) + '\n' for key in sorted(documents)).encode('utf-8')
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
    # Retain integrity entries for documents imported on an earlier run.
    all_hashes = {**previous_hashes, **hashes}
    unchanged = marker.get('ready') and all((destination / name).is_file() and hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest for name, digest in all_hashes.items())
    if not unchanged:
        save(destination / 'export.json', {**marker, 'ready': False})
        for name, content in files.items():
            write_changed(destination / name, content, previous_hashes.get(name))
    export = {'schema_version': 2, 'batch_id': batch_id, 'revision': data['revision'],
              'author_key': archive_identity, 'author_name': data['source'].get('name'),
              'state': data['state'], 'documents_count': count, 'author_documents_count': len(documents),
              'documents_sha256': hashes['documents.jsonl'], 'documents_file': str(index_path),
              'documents_relative_path': 'documents.jsonl', 'files_sha256': all_hashes,
              'exported_at': datetime.now(timezone.utc).isoformat(), 'folder': str(destination),
              'generation': marker.get('generation') if unchanged else uuid.uuid4().hex,
              'reused': bool(unchanged), 'ready': True}
    save(destination / 'export.json', export)
    data['last_export'] = export
    save(folder / 'author-batch.json', data)
    return export
