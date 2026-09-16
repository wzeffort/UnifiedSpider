"""FastAPI local service with a bounded background queue and explicit user sessions."""
import html
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from core import csv_bytes, extract, preview_html, validate_url
from storage import ROOT, DATA, read, save
from jobs import submit, cancel, public_jobs, job_folder, shutdown, kill_tree
from site_access import describe
from export_names import export_name, disposition

TOKEN = secrets.token_urlsafe(32)
SESSION_PROCESS = None
SESSION_ID = None
SESSION_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    yield
    shutdown()
    if SESSION_PROCESS and SESSION_PROCESS.poll() is None:
        kill_tree(SESSION_PROCESS)


app = FastAPI(title='UnifiedSpider API', version='2.1', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


@app.middleware('http')
async def local_request(request: Request, call_next):
    if request.method == 'POST' and request.headers.get('x-token') != TOKEN:
        return JSONResponse({'error': '请刷新页面后重试'}, status_code=403)
    if request.method == 'POST':
        body = await request.body()
        if len(body) > 2_000_000:
            return JSONResponse({'error': '内容过大，最多支持 2 MB'}, status_code=413)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(Exception)
async def failure(request, exc):
    return JSONResponse({'error': str(exc)}, status_code=400)


@app.get('/', response_class=HTMLResponse)
def index():
    return (ROOT / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN)


@app.get('/health')
def health():
    return {'app': 'UnifiedSpider', 'ok': True, 'version': '2.1',
            'backend': 'FastAPI', 'engines': ['Scrapy', 'Crawl4AI', 'Playwright']}


@app.get('/api/jobs')
def jobs():
    return public_jobs()


@app.get('/api/site-info')
def site_info(url: str, use_session: bool = True):
    return describe(validate_url(url), use_session)


@app.post('/api/jobs')
def create(config: dict):
    return {'id': submit(config)}


@app.post('/api/cancel/{job_id}')
def stop(job_id: str):
    cancel(job_id)
    return {'ok': True}


@app.post('/api/resume/{job_id}')
def resume(job_id: str):
    return {'id': submit(resume_id=str(uuid.UUID(job_id)))}


def get_result(job_id):
    data = read(job_folder(job_id) / 'result.json')
    if not data or not data.get('pages'):
        raise ValueError((data or {}).get('error') or '该任务尚无成功采集的内容')
    from document_view import document_data
    return document_data(data)


@app.get('/api/result/{job_id}')
def result(job_id: str):
    data = get_result(job_id)
    return {'rows': data['rows'], 'failures': data.get('failures', []),
            'download_names': {fmt: export_name(data, read(job_folder(job_id) / 'status.json', {}), job_id, fmt) for fmt in ('txt', 'csv', 'json', 'md', 'zip')},
            'pages': [{k: v for k, v in page.items() if k != 'html'} for page in data['pages']],
            'preview': preview_html(data['pages'][0].get('content_html') or data['pages'][0]['html'])}


def download(content, mime, filename):
    return Response(content=content, media_type=mime,
                    headers={'Content-Disposition': disposition(filename)})


@app.get('/api/export/{job_id}')
def export(job_id: str, format: str = 'json'):
    data = get_result(job_id)
    filename = export_name(data, read(job_folder(job_id) / 'status.json', {}), job_id, format)
    if format == 'zip':
        from image_assets import offline_bundle
        return download(offline_bundle(data, job_folder(job_id)), 'application/zip', filename)
    if format == 'csv':
        return download(csv_bytes(data['rows']), 'text/csv; charset=utf-8', filename)
    if format in ('md', 'txt'):
        from bs4 import BeautifulSoup
        parts = []
        for page in data['pages']:
            text = page['markdown'] if format == 'md' else page.get('text', BeautifulSoup(preview_html(page['html']), 'html.parser').get_text('\n', strip=True))
            title = str(page.get('title', '网页资料')).replace('\n', ' ')
            heading = '# ' + title if format == 'md' else title
            notice = '\n\n说明：' + '；'.join(page.get('notes', [])) if page.get('notes') else ''
            parts.append(heading + '\n\n来源：' + page['url'] + notice + '\n\n' + text)
        return download('\n\n---\n\n'.join(parts).encode('utf-8-sig'), 'text/plain; charset=utf-8' if format == 'txt' else 'text/markdown; charset=utf-8', filename)
    if format != 'json':
        raise ValueError('不支持的下载格式')
    public = {'rows': data['rows'], 'failures': data.get('failures', []),
              'pages': [{k: v for k, v in page.items() if k != 'html'} for page in data['pages']]}
    return download((json.dumps(public, ensure_ascii=False, indent=2) + '\n').encode('utf-8'), 'application/json', filename)


@app.post('/api/import')
def import_text(config: dict):
    content = str(config.get('text', '')).strip()
    if not content:
        raise ValueError('请先粘贴网页正文')
    url = str(config.get('url', '')).strip()
    if url:
        validate_url(url)
    title = str(config.get('title', '')).strip() or '手动保存的网页资料'
    job_id = str(uuid.uuid4())
    folder = job_folder(job_id)
    folder.mkdir()
    save(folder / 'result.json', {'pages': [{'url': url, 'title': title, 'html': '<h1>' + html.escape(title) + '</h1><pre>' + html.escape(content) + '</pre>', 'markdown': content, 'text': content}],
        'rows': [{'来源网址': url, '标题': title, '正文': content}]})
    save(folder / 'status.json', {'id': job_id, 'url': url, 'status': 'done', 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'pages': 1, 'rows': 1, 'source': 'manual'})
    return {'id': job_id}


@app.post('/api/extract')
def extract_fields(config: dict):
    from jobs import ACTIVE
    job_id = str(uuid.UUID(config['id']))
    if job_id in ACTIVE:
        raise ValueError('请等待任务结束后再修改字段')
    data = get_result(job_id)
    rows = []
    for page in data['pages']:
        rows.extend(extract(page.get('content_html') or page['html'], page['url'], config['fields'], config.get('row', '')))
    data['rows'] = rows
    save(job_folder(job_id) / 'result.json', data)
    status = read(job_folder(job_id) / 'status.json')
    if status:
        status['rows'] = len(rows)
        save(job_folder(job_id) / 'status.json', status)
    return {'rows': rows}


@app.post('/api/session/open')
def open_session(config: dict):
    global SESSION_PROCESS, SESSION_ID
    url = validate_url(config['url'])
    with SESSION_LOCK:
        if SESSION_PROCESS and SESSION_PROCESS.poll() is None:
            raise ValueError('已有人工操作浏览器，请先保存或关闭')
        job_id = str(uuid.uuid4())
        folder = job_folder(job_id)
        folder.mkdir()
        save(folder / 'session-config.json', {'url': url})
        save(folder / 'session-status.json', {'state': 'opening', 'message': '正在打开可见浏览器…'})
        with (folder / 'session.log').open('w', encoding='utf-8') as log:
            SESSION_PROCESS = subprocess.Popen([sys.executable, str(ROOT / 'session_worker.py'), job_id],
                cwd=ROOT, stdout=log, stderr=log, env={**os.environ, 'PYTHONUTF8': '1'})
        SESSION_ID = job_id
        return {'id': job_id}


@app.post('/api/cookies/import')
def import_cookies(config: dict):
    from cookie_state import store_state
    url = validate_url(config.get('url', ''))
    with SESSION_LOCK:
        if SESSION_PROCESS and SESSION_PROCESS.poll() is None:
            raise ValueError('请先关闭操作浏览器再导入，避免旧状态覆盖新状态')
        return store_state(url, config.get('data'))


@app.get('/api/session/{job_id}')
def session_status(job_id: str):
    status = read(job_folder(job_id) / 'session-status.json', {'state': 'closed', 'message': '浏览器会话不存在'})
    if status['state'] in ('opening', 'waiting') and (SESSION_ID != job_id or SESSION_PROCESS.poll() is not None):
        status.update(state='closed', message='操作浏览器已结束，请重新打开')
    return status


@app.post('/api/session/{job_id}/{action}')
def session_action(job_id: str, action: str):
    if job_id != SESSION_ID or not SESSION_PROCESS or SESSION_PROCESS.poll() is not None:
        raise ValueError('浏览器会话已结束，请重新打开')
    if action not in ('confirm', 'cancel', 'state'):
        raise ValueError('不支持的操作')
    save(job_folder(job_id) / ('session-' + action), True)
    return {'ok': True}


if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('SPIDER_PORT', '18765'))
    if '--no-browser' not in sys.argv:
        threading.Timer(1, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
