"""Two provider lanes; one request per lane and shared in-flight hash dedup."""
import hashlib
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, Future

LOCK=threading.RLock()
POOLS={name:ThreadPoolExecutor(max_workers=1,thread_name_prefix='ocr-'+name) for name in ('local','official')}
PENDING={'local':0,'official':0}
INFLIGHT={}


def submit(path):
    import mineru_client
    import mineru_selfhost
    from storage import read,save
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with LOCK:
        if digest in INFLIGHT:return INFLIGHT[digest]
        # Retain paid, previously completed official results after migration.
        cache_path=mineru_client.CACHE/(digest+'-hybrid-v1.json')
        official=read(mineru_client.CACHE/(digest+'-vlm-v1.json'),{})
        cached=read(cache_path,{}) or official
        if cached.get('result'):
            done=Future();done.set_result(cached['result']);return done
        # Resume an uploaded official job instead of submitting it to another provider.
        lane='official' if official.get('batch_id') and not official.get('failed') else min(PENDING,key=PENDING.get)
        PENDING[lane]+=1
        fn=mineru_selfhost.recognize if lane=='local' else mineru_client.recognize_official
        future=POOLS[lane].submit(fn,path,600)
        INFLIGHT[digest]=future
        def complete(_):
            with LOCK:
                try:
                    if not future.cancelled() and future.exception() is None:
                        mineru_client.CACHE.mkdir(parents=True,exist_ok=True)
                        save(cache_path,{'result':future.result()})
                except OSError:
                    logging.getLogger(__name__).warning('OCR cache write failed')
                finally:
                    PENDING[lane]-=1
                    INFLIGHT.pop(digest,None)
        future.add_done_callback(complete)
        return future
