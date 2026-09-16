"""Local access state; never exposes cookie values or claims a login is valid."""
import math
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlsplit
from storage import DATA, read, session_path

DB = DATA / 'access.sqlite3'


def origin(url):
    parsed = urlsplit(url)
    return f'{parsed.scheme}://{parsed.netloc}'


@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=10)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS cooldown (origin TEXT PRIMARY KEY, until REAL, reason TEXT)')
            yield db
    finally:
        db.close()


def restrict(url, reason, seconds=300):
    with connection() as db:
        db.execute('INSERT INTO cooldown VALUES (?, ?, ?) ON CONFLICT(origin) DO UPDATE SET until=excluded.until, reason=excluded.reason',
                   (origin(url), time.time() + seconds, reason))


def clear_restriction(url):
    with connection() as db:
        db.execute('DELETE FROM cooldown WHERE origin=?', (origin(url),))


def remaining(url):
    with connection() as db:
        row = db.execute('SELECT until FROM cooldown WHERE origin=?', (origin(url),)).fetchone()
    return max(0, math.ceil(row[0] - time.time())) if row else 0


def applicable_state(url):
    state = read(session_path(url), {})
    parsed = urlsplit(url)
    host, now = parsed.hostname, time.time()
    for cookie in state.get('cookies', []):
        domain = cookie.get('domain', '')
        matches = host == domain.lstrip('.') or (domain.startswith('.') and host.endswith(domain))
        expires = cookie.get('expires', -1)
        path = cookie.get('path', '/')
        request_path = parsed.path or '/'
        path_matches = request_path == path or (request_path.startswith(path) and (path.endswith('/') or request_path[len(path):].startswith('/')))
        if matches and path_matches and (expires == -1 or expires > now) and (not cookie.get('secure') or parsed.scheme == 'https'):
            return True
    return any(item.get('origin') == origin(url) and (item.get('localStorage') or item.get('indexedDB'))
               for item in state.get('origins', []))


def needs_confirmation(url, use_session=True):
    p = urlsplit(url)
    return p.hostname == 'www.zhihu.com' and ('/question/' in p.path or '/answer/' in p.path) and not (use_session and applicable_state(url))


def describe(url, use_session=True):
    available = applicable_state(url)
    seconds = remaining(url)
    confirmation = needs_confirmation(url, use_session)
    if seconds:
        message = f'本站刚刚限制了访问，自动采集暂停 {seconds} 秒。可打开操作浏览器自行查看。'
    elif confirmation:
        message = '这个知乎回答尚无可用的已保存状态。建议先打开操作浏览器，看到正文后保存；不代表必须登录，也不会代填密码。'
    elif available and use_session:
        message = '将使用本工具保存的本站浏览状态。是否仍登录有效，需要网站实际响应确认。'
    elif not use_session:
        message = '已关闭状态复用，本次以未登录方式访问。'
    else:
        message = '尚无可用的本站浏览状态，本次将以未登录方式访问。勾选复用不会自动登录。'
    return {'origin': origin(url), 'state_file_exists': session_path(url).exists(),
            'state_available': available, 'use_session': use_session, 'cooldown_seconds': seconds,
            'suggest_manual': bool(seconds or confirmation), 'message': message}
