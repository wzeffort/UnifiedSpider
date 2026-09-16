"""Validate user-provided state without returning or logging credential values."""
import math
import time
from urllib.parse import urlsplit
import tldextract
from storage import save, session_path

SUFFIX = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


def scoped_state(url, payload):
    host = urlsplit(url).hostname
    origin = f'{urlsplit(url).scheme}://{urlsplit(url).netloc}'
    raw = payload if isinstance(payload, list) else payload.get('cookies', []) if isinstance(payload, dict) else None
    if not isinstance(raw, list) or len(raw) > 1000:
        raise ValueError('请选择 Cookie JSON 数组或浏览器状态 JSON 文件，最多 1000 条')
    cookies, ignored = {}, 0
    for item in raw:
        try:
            if not isinstance(item, dict):
                raise ValueError()
            domain = str(item.get('domain', '')).lower()
            bare = domain.lstrip('.')
            if not bare or not (host == bare or (domain.startswith('.') and host.endswith(domain))):
                raise ValueError()
            if SUFFIX(bare).suffix == bare:
                raise ValueError()
            expiry = float(item.get('expires', item.get('expirationDate', -1)))
            if item.get('session') is True:
                expiry = -1
            if not math.isfinite(expiry) or (expiry != -1 and expiry <= time.time()):
                raise ValueError()
            name, value = item.get('name'), item.get('value')
            if not isinstance(name, str) or not isinstance(value, str) or not name or len(name) + len(value) > 16384:
                raise ValueError()
            if any(ord(c) < 32 or ord(c) == 127 for c in name + value):
                raise ValueError()
            path = item.get('path', '/')
            if not isinstance(path, str) or not path.startswith('/'):
                raise ValueError()
            if item.get('partitionKey'):
                raise ValueError()  # Do not accidentally turn partitioned cookies into global cookies.
            same_site = {'strict': 'Strict', 'lax': 'Lax', 'none': 'None', 'no_restriction': 'None', 'unspecified': 'Lax'}.get(str(item.get('sameSite', 'Lax')).lower(), 'Lax')
            cookie = {'name': name, 'value': value, 'domain': bare if item.get('hostOnly') else domain,
                      'path': path, 'expires': expiry, 'secure': bool(item.get('secure', False)),
                      'httpOnly': bool(item.get('httpOnly', False)), 'sameSite': same_site}
            if same_site == 'None' and not cookie['secure']:
                cookie['sameSite'] = 'Lax'
            cookies[(cookie['domain'], path, name)] = cookie
        except (ValueError, TypeError, OverflowError):
            ignored += 1
    origins = []
    if isinstance(payload, dict):
        for item in payload.get('origins', []):
            if isinstance(item, dict) and item.get('origin') == origin:
                origins.append(item)
    if not cookies and not any(i.get('localStorage') or i.get('indexedDB') for i in origins):
        raise ValueError('没有找到本站未过期的 Cookie 或站点存储，原状态未覆盖。请在已登录的目标网页导出。')
    return {'cookies': list(cookies.values()), 'origins': origins}, ignored


def store_state(url, payload):
    state, ignored = scoped_state(url, payload)
    save(session_path(url), state)
    return {'cookie_count': len(state['cookies']), 'ignored_count': ignored,
            'message': f'已保存本站 {len(state["cookies"])} 条 Cookie。是否登录有效仍需网站确认；这不会解除访问限制。'}
