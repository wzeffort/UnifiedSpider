"""Serialized, durable post-capture OCR and export orchestration."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from storage import save

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='author-output')
PENDING = set()
GUARD = threading.Lock()
STREAMING = set()


def enqueue_article(batch_id, url):
    key = (batch_id, url)
    with GUARD:
        if key in STREAMING:
            return
        STREAMING.add(key)
        POOL.submit(recognize_article, batch_id, url)


def recognize_article(batch_id, url):
    import author_batch as batch
    import article_store
    import rag_assets
    folder = batch.job_folder(batch_id)
    acquired = False
    try:
        while True:
            with batch.LOCK:
                if batch.load(batch_id)['state']=='cancelled':
                    return
            with rag_assets.GUARD:
                if not rag_assets.ACTIVE:
                    rag_assets.ACTIVE.add(str(folder))
                    acquired = True
                    break
            time.sleep(.25)
        page = article_store.get(folder, url)
        if page:
            # No queue revision changes: OCR completion must not invalidate a browser reply.
            rag_assets.run(batch_id, folder, 'mineru', selected_pages=[page])
    finally:
        if acquired:
            with rag_assets.GUARD:
                rag_assets.ACTIVE.discard(str(folder))
        with GUARD:
            STREAMING.discard((batch_id, url))


def enqueue(data):
    import author_batch as batch
    with GUARD:
        if data['id'] in PENDING:
            return
        data.update(auto_state='queued', auto_message='正文采集结束，等待自动识别图片。')
        save(batch.job_folder(data['id']) / 'author-batch.json', data)
        PENDING.add(data['id'])
        POOL.submit(run, data['id'])


def update(batch_id, state, message):
    import author_batch as batch
    with batch.LOCK:
        data = batch.load(batch_id)
        data.update(auto_state=state, auto_message=message)
        save(batch.job_folder(batch_id) / 'author-batch.json', data)
        return data


def run(batch_id):
    import author_batch as batch
    import rag_assets
    try:
        update(batch_id, 'recognizing', '正在自动下载并识别正文图片。')
        # The shared image worker is deliberately serial to limit API concurrency.
        while True:
            try:
                rag_assets.start(batch_id, ocr=True, pipeline=True)
                break
            except ValueError:
                if not rag_assets.ACTIVE:
                    raise
                time.sleep(1)
        folder = batch.job_folder(batch_id)
        while str(folder) in rag_assets.ACTIVE:
            time.sleep(.25)
        result = rag_assets.status(folder)
        if result['state'] != 'finished':
            raise ValueError(result.get('message', '图片处理未完成'))
        data = update(batch_id, 'saving', '图片处理结束，正在自动保存资料。')
        if data['output_settings']['mode'] == 'folder':
            batch.save_to_folder(batch_id, data['output_settings'])
        failed = result.get('failed_images', 0)
        update(batch_id, 'partial' if failed else 'done',
               f'资料已处理；{failed} 张图片未识别成功，可重试识别并重新保存。' if failed else
               ('已自动识别并保存到所选目录。' if data['output_settings']['mode'] == 'folder' else '识别完成，等待浏览器下载资料包。'))
    except Exception as exc:
        update(batch_id, 'failed', '自动处理未完成：' + str(exc)[:200] + '。可重试识别并保存。')
    finally:
        with GUARD:
            PENDING.discard(batch_id)


def enqueue_cancelled(data):
    """Export retained data after in-flight OCR, without starting more OCR."""
    import author_batch as batch
    with GUARD:
        if data['id'] in PENDING:
            return
        data.update(auto_state='queued', auto_message='已取消后续采集，等待当前图片处理结束后自动合并已有资料。')
        save(batch.job_folder(data['id']) / 'author-batch.json', data)
        PENDING.add(data['id'])
        POOL.submit(export_cancelled, data['id'])


def export_cancelled(batch_id):
    import author_batch as batch
    import rag_assets
    try:
        folder = batch.job_folder(batch_id)
        while str(folder) in rag_assets.ACTIVE:
            time.sleep(.25)
        data = update(batch_id, 'saving', '已停止采集，正在合并导出已入库资料。')
        batch.save_to_folder(batch_id, data['output_settings'])
        update(batch_id, 'done', '任务已取消；已有资料已自动合并保存，未重新下载或识别。')
    except Exception as exc:
        update(batch_id, 'failed', '取消后的自动导出失败：'+str(exc)[:200]+'；已有数据保留，可点击保存资料重试。')
    finally:
        with GUARD:
            PENDING.discard(batch_id)


def recover():
    """Called once at startup, resuming jobs whose process was interrupted."""
    import author_batch as batch
    from storage import DATA, read
    for path in DATA.glob('*/author-batch.json'):
        data = read(path, {})
        if data.get('state')=='cancelled':
            if data.get('auto_state') in ('queued','saving'):
                enqueue_cancelled(data)
            continue
        if data.get('auto_state') in ('queued', 'recognizing', 'saving'):
            enqueue(data)
        elif data.get('auto_state') == 'streaming':
            import article_store
            for url in article_store.urls(path.parent):
                enqueue_article(data['id'], url)
