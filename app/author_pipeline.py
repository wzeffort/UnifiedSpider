"""Serialized, durable post-capture OCR and export orchestration."""
from collections import OrderedDict, deque
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from storage import save

class FairPool:
    """One slice at a time, rotating authors instead of draining one author's backlog."""
    def __init__(self):
        self.lock = threading.Lock()
        self.queues = OrderedDict()
        self.running = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='author-output')

    def submit(self, fn, batch_id, *args):
        with self.lock:
            self.queues.setdefault(batch_id, deque()).append((fn, args))
            if not self.running:
                self.running = True
                self.executor.submit(self.drain)

    def drain(self):
        while True:
            with self.lock:
                if not self.queues:
                    self.running = False
                    return
                batch_id, jobs = self.queues.popitem(last=False)
                fn, args = jobs.popleft()
                if jobs:
                    self.queues[batch_id] = jobs
            try:
                fn(batch_id, *args)
            except Exception:
                logging.getLogger(__name__).exception('Author output slice failed')


POOL = FairPool()
SLICE_IMAGES = 4
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


def recognize_article(batch_id, url, offset=0):
    import author_batch as batch
    import article_store
    import rag_assets
    folder = batch.job_folder(batch_id)
    acquired = False
    again = False
    try:
        if batch_id in PENDING:
            return  # The final pass owns all remaining images for this author.
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
            result = rag_assets.run(batch_id, folder, 'mineru', selected_pages=[page],
                                    image_offset=offset, max_images=SLICE_IMAGES)
            if result.get('state') == 'queued':
                again = True
                POOL.submit(recognize_article, batch_id, url, result['next_image'])
    finally:
        if acquired:
            with rag_assets.GUARD:
                rag_assets.ACTIVE.discard(str(folder))
        if not again:
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


def run(batch_id, offset=0):
    import author_batch as batch
    import rag_assets
    again = False
    folder = batch.job_folder(batch_id)
    try:
        # Export the current text before waiting for external OCR. Each subsequent
        # slice merges its new results into the same author's directory.
        if rag_assets.ACTIVE:
            again = True
            POOL.submit(run, batch_id, offset)
            time.sleep(.25)
            return
        data = batch.load(batch_id)
        if offset == 0 and data['output_settings']['mode'] == 'folder':
            batch.save_to_folder(batch_id, data['output_settings'])
        with rag_assets.GUARD:
            if rag_assets.ACTIVE:
                again = True
                POOL.submit(run, batch_id, offset)
                time.sleep(.25)
                return
            rag_assets.ACTIVE.add(str(folder))
        update(batch_id, 'recognizing', '正在分批识别图片；正文已可使用。')
        result = rag_assets.run(batch_id, folder, 'mineru',
                                image_offset=offset, max_images=SLICE_IMAGES)
        if result['state'] not in ('queued', 'finished'):
            raise ValueError(result.get('message', '图片处理未完成'))
        data = update(batch_id, 'saving', '正在将本批识别结果更新到作者目录。')
        if data['output_settings']['mode'] == 'folder':
            batch.save_to_folder(batch_id, data['output_settings'])
        if result['state'] == 'queued':
            update(batch_id, 'queued', '正文和已识别图片已保存，剩余图片排队继续。')
            again = True
            POOL.submit(run, batch_id, result['next_image'])
        else:
            failed = result.get('failed_images', 0)
            update(batch_id, 'partial' if failed else 'done',
                   f'资料已保存；{failed} 张图片失败或超时，可稍后重试。' if failed else
                   ('已自动识别并保存到所选目录。' if data['output_settings']['mode'] == 'folder' else '识别完成，等待浏览器下载资料包。'))
    except Exception as exc:
        update(batch_id, 'failed', '自动处理未完成：' + str(exc)[:200] + '。已有正文和识别结果保留，可重试。')
    finally:
        if not again:
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
