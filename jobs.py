import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from core import validate_url, extract
from storage import ROOT, DATA, read, save

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='spider-job')
LOCK = threading.RLock()
ACTIVE = set()
PROCESSES = {}


def job_folder(job_id):
    return DATA / str(uuid.UUID(job_id))


def public_jobs():
    jobs = []
    for file in DATA.glob('*/status.json'):
        job = read(file)
        if not job:
            continue
        if job['status'] in ('running', 'queued') and job['id'] not in ACTIVE:
            result = read(file.parent / 'result.json', {})
            job.update(status='interrupted', pages=len(result.get('pages', [])), error='服务已重启，可继续采集，已有结果已保留')
        progress = read(file.parent / 'progress.json', {})
        job['progress'] = progress
        jobs.append(job)
    return sorted(jobs, key=lambda j: j['created'], reverse=True)


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
    else:
        proc.kill()
    proc.wait(timeout=10)


def execute(job_id):
    folder = job_folder(job_id)
    status = read(folder / 'status.json')
    try:
        if (folder / 'cancel').exists():
            return
        status.update(status='running', error=None)
        save(folder / 'status.json', status)
        with (folder / 'worker.log').open('a', encoding='utf-8') as log:
            proc = subprocess.Popen([sys.executable, str(ROOT / 'worker.py'), str(folder / 'config.json'), str(folder / 'result.json')],
                cwd=ROOT, stdout=log, stderr=log, env={**os.environ, 'PYTHONUTF8': '1'})
            with LOCK:
                PROCESSES[job_id] = proc
            deadline = time.monotonic() + 1800
            while proc.poll() is None:
                if (folder / 'cancel').exists() or time.monotonic() > deadline:
                    kill_tree(proc)
                    if not (folder / 'cancel').exists():
                        status['error'] = '超过 30 分钟，已保留完成部分，可继续采集'
                    break
                time.sleep(.25)
        result = read(folder / 'result.json', {})
        if proc.returncode != 0 and not result.get('error') and not (folder / 'cancel').exists():
            status['error'] = status.get('error') or '采集进程异常退出，已保存完成部分，可继续采集'
        pages, failures = result.get('pages', []), result.get('failures', [])
        if (folder / 'cancel').exists():
            state = 'cancelled'
        elif status.get('error'):
            state = 'interrupted'
        elif pages:
            state = 'partial' if failures or result.get('error') else 'done'
        elif any(f.get('needs_user') for f in failures):
            state = 'needs_user'
        else:
            state = 'failed'
        status.update(status=state, pages=len(pages), rows=len(result.get('rows', [])),
                      failed_pages=len(failures), failures=failures,
                      error=status.get('error') or result.get('error') or (failures[0]['reason'] if failures else None))
        if not result and not status['error'] and state != 'cancelled':
            status['error'] = '采集进程未返回结果，请查看任务日志'
    except Exception as exc:
        status.update(status='failed', error=str(exc))
    finally:
        saved = read(folder / 'result.json', {})
        status['pages'] = len(saved.get('pages', []))
        status['rows'] = len(saved.get('rows', []))
        if (folder / 'cancel').exists():
            status['status'] = 'cancelled'
        save(folder / 'status.json', status)
        with LOCK:
            ACTIVE.discard(job_id)
            PROCESSES.pop(job_id, None)


def normalize(config):
    urls = config.get('urls') or [config.get('url', '')]
    if isinstance(urls, str):
        urls = urls.splitlines()
    urls = list(dict.fromkeys(validate_url(u.strip()) for u in urls if u.strip()))
    if not urls or len(urls) > 100:
        raise ValueError('请输入 1–100 个网址')
    config.update(url=urls[0], urls=urls)
    config['limit'] = max(len(urls), min(100, max(1, int(config.get('limit', 1)))))
    config.setdefault('engine', 'auto')
    if config['engine'] not in ('auto', 'scrapy', 'browser'):
        raise ValueError('不支持的采集引擎')
    config.setdefault('fields', [])
    config.setdefault('row', '')
    if len(config['fields']) > 50:
        raise ValueError('最多支持 50 个字段')
    names = [field.get('name', '').strip() for field in config['fields']]
    if len(names) != len(set(names)) or any(not name or name == '来源网址' for name in names):
        raise ValueError('字段名称不能为空、不能重复，也不能使用保留名称“来源网址”')
    from bs4 import BeautifulSoup
    for selector in (config.get('next'), config.get('wait_for')):
        if selector:
            BeautifulSoup('', 'html.parser').select(selector)
    extract('', config['url'], config['fields'], config['row'])
    return config


def submit(config=None, resume_id=None):
    with LOCK:
        if len(ACTIVE) >= 20:
            raise ValueError('排队任务已达 20 个，请等待任务完成')
        if resume_id:
            folder = job_folder(resume_id)
            if resume_id in ACTIVE:
                raise ValueError('该任务正在执行')
            config = read(folder / 'config.json')
            if not config:
                raise ValueError('该记录不是自动采集任务，无法重试')
            job_id = resume_id
        else:
            config = normalize(config)
            job_id = str(uuid.uuid4())
            folder = job_folder(job_id)
            folder.mkdir()
            save(folder / 'config.json', config)
        (folder / 'cancel').unlink(missing_ok=True)
        save(folder / 'status.json', {'id': job_id, 'url': config['url'], 'status': 'queued',
             'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'engine': config.get('engine', 'auto')})
        ACTIVE.add(job_id)
        POOL.submit(execute, job_id)
        return job_id


def cancel(job_id):
    folder = job_folder(job_id)
    if job_id not in ACTIVE:
        raise ValueError('该任务已结束')
    save(folder / 'cancel', True)


def shutdown():
    with LOCK:
        for proc in list(PROCESSES.values()):
            kill_tree(proc)
    POOL.shutdown(wait=False, cancel_futures=True)
