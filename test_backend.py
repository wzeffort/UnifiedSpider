"""Integration tests against the running local service and controlled fixture sites."""
import json
import re
import threading
import time
import urllib.request
import urllib.error
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from storage import save, read, session_path
from jobs import job_folder
from session_worker import run as session_run
from site_access import clear_restriction, remaining

BASE = 'http://127.0.0.1:18765'
COUNTS = {}
ALLOW_BLOCKED = False
TEXT = 'A detailed fixture article with meaningful visible text for extraction and browser testing. ' * 10


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        global ALLOW_BLOCKED
        COUNTS[self.path] = COUNTS.get(self.path, 0) + 1
        code = 200
        body = '<main><h1>Fixture article</h1><p>' + TEXT + '</p></main>'
        if self.path == '/dynamic':
            body = '<main id="app"></main><script>setTimeout(()=>document.getElementById("app").textContent=' + json.dumps('Rendered content. ' + TEXT) + ',150)</script>'
        elif self.path == '/partial':
            body += '<a href="/blocked">Other article</a>'
        elif self.path == '/blocked' and not ALLOW_BLOCKED:
            code, body = 403, '<h1>Access denied</h1>'
        elif self.path == '/retry' and COUNTS[self.path] < 2:
            code, body = 503, '<h1>Temporary error</h1>'
        elif self.path == '/slow':
            time.sleep(4)
        elif self.path == '/private':
            if 'fixture_session=ok' not in self.headers.get('Cookie', ''):
                code, body = 401, '<h1>Sign in to continue</h1>'
            else:
                body = '<main><h1>Private fixture article</h1><p>' + TEXT + '</p></main>'
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        if self.path == '/grant':
            self.send_header('Set-Cookie', 'fixture_session=ok; Path=/; SameSite=Lax')
        self.end_headers()
        try:
            self.wfile.write(('<html><head><title>Fixture</title></head><body>' + body + '</body></html>').encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


def request(path, data=None, token=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json', 'X-Token': token or TOKEN})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def wait(job_id):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        job = next(j for j in request('/api/jobs') if j['id'] == job_id)
        if job['status'] not in ('running', 'queued'):
            return job
        time.sleep(.3)
    raise AssertionError('Job timeout ' + job_id)


def start(path, **kwargs):
    return request('/api/jobs', {'url': SITE + path, **kwargs})['id']


with urllib.request.urlopen(BASE) as res:
    TOKEN = re.search(r"const token='([^']+)'", res.read().decode()).group(1)
server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
threading.Thread(target=server.serve_forever, daemon=True).start()
SITE = 'http://127.0.0.1:' + str(server.server_port)
try:
    try:
        request('/api/jobs', {'url': SITE}, token='wrong')
        raise AssertionError('Missing CSRF protection')
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    print('Local request protection: PASS')

    job_id = start('/dynamic')
    assert wait(job_id)['status'] == 'done'
    result = request('/api/result/' + job_id)
    assert result['pages'][0]['engine'] == 'crawl4ai-playwright'
    assert 'Rendered content' in result['rows'][0]['正文']
    print('Automatic dynamic-browser fallback: PASS')

    job_id = start('/retry', engine='scrapy')
    assert wait(job_id)['status'] == 'done'
    assert COUNTS['/retry'] == 2, COUNTS
    print('Scrapy 503 retry: PASS')

    job_id = start('/partial', site=True, limit=2)
    partial = wait(job_id)
    assert partial['status'] == 'partial', partial
    assert partial['pages'] == 1 and partial['failed_pages'] == 1
    assert COUNTS['/blocked'] == 1, '403 should not be repeatedly retried'
    assert request('/api/result/' + job_id)['rows']
    assert remaining(SITE) > 0
    blocked_count = COUNTS['/blocked']
    paused = wait(start('/blocked'))
    assert paused['error'] == 'cooldown', paused
    assert COUNTS['/blocked'] == blocked_count, 'Cooldown must prevent requests across jobs'
    # The fixture operator removes the simulated restriction before resuming.
    clear_restriction(SITE)
    ALLOW_BLOCKED = True
    request('/api/resume/' + job_id, {})
    resumed = wait(job_id)
    assert resumed['status'] == 'done' and resumed['pages'] == 2, resumed
    assert COUNTS['/partial'] == 1, 'Resume should keep already completed pages'
    print('Partial result preservation and resume without refetch: PASS')

    ALLOW_BLOCKED = False
    blocked = wait(start('/blocked'))
    assert blocked['status'] == 'needs_user', blocked
    print('403 identified as requiring user action: PASS')
    clear_restriction(SITE)

    batch = [start('/slow') for _ in range(3)]
    queued = next(j for j in request('/api/jobs') if j['id'] == batch[2])
    assert queued['status'] == 'queued', queued
    request('/api/cancel/' + batch[2], {})
    for job in batch[:2]:
        assert wait(job)['status'] == 'done'
    assert wait(batch[2])['status'] == 'cancelled'
    print('Two-worker queue and queued cancellation: PASS')

    folder = job_folder(str(uuid.uuid4()))
    folder.mkdir()
    save(folder / 'session-config.json', {'url': SITE + '/grant'})
    thread = threading.Thread(target=session_run, args=(folder,), kwargs={'headless': True}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while read(folder / 'session-status.json', {}).get('state') != 'waiting':
        assert time.monotonic() < deadline
        time.sleep(.1)
    assert not (folder / 'result.json').exists(), 'Must wait for explicit user confirmation'
    save(folder / 'session-state', True)
    deadline = time.monotonic() + 10
    while 'cookie_count' not in read(folder / 'session-status.json', {}):
        assert time.monotonic() < deadline
        time.sleep(.1)
    assert read(folder / 'session-status.json')['cookie_count'] > 0
    assert not (folder / 'result.json').exists(), 'Saving cookies must not capture article'
    save(folder / 'session-confirm', True)
    thread.join(30)
    assert read(folder / 'session-status.json')['state'] == 'saved'
    assert session_path(SITE).exists()
    private = start('/private', engine='auto')
    assert wait(private)['status'] == 'done'
    assert 'Private fixture article' in request('/api/result/' + private)['rows'][0]['正文']
    print('Confirmed browser capture and saved-session reuse: PASS')

    # Exercise the actual UI-triggered headed browser subprocess as well.
    browser_id = request('/api/session/open', {'url': SITE + '/grant'})['id']
    deadline = time.monotonic() + 40
    while True:
        state = request('/api/session/' + browser_id)
        if state['state'] == 'waiting':
            break
        assert state['state'] != 'closed', state
        assert time.monotonic() < deadline, state
        time.sleep(.2)
    request('/api/session/' + browser_id + '/confirm', {})
    while True:
        state = request('/api/session/' + browser_id)
        if state['state'] == 'saved':
            break
        assert time.monotonic() < deadline, state
        time.sleep(.2)
    assert request('/api/result/' + browser_id)['pages'][0]['engine'] == 'manual-browser'
    print('Visible browser open / confirm / capture API: PASS')
finally:
    server.shutdown()
