"""Validate user-provided state without returning or logging credential values."""
import math
import json
import time
from urllib.parse import urlsplit
import tldextract
from storage import save, read, session_path
from site_access import applicable_state, clear_restriction, remaining, denial_count

SUFFIX = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


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


def effective_credentials(url, state):
    # Ignore export ordering and expiry-only changes. Only compare credentials
    # actually applicable to this URL; never expose their values in responses.
    cookies = {}
    for cookie in state.get('cookies', []):
        if applicable_state(url, {'cookies': [cookie]}):
            key = (cookie.get('domain'), cookie.get('path', '/'), cookie.get('name'))
            cookies[key] = cookie.get('value')
    origins = sorted((item for item in state.get('origins', [])
                      if applicable_state(url, {'origins': [item]})), key=lambda i: i['origin'])
    return cookies, json.dumps(origins, sort_keys=True, ensure_ascii=False)


def store_state(url, payload, allow_retry=False):
    state, ignored = scoped_state(url, payload)
    old = read(session_path(url), {}) or {}
    previous_cookies, previous_origins = effective_credentials(url, old)
    cookies, origins = effective_credentials(url, state)
    changed = any(key not in previous_cookies or previous_cookies[key] != value
                  for key, value in cookies.items()) or (origins != '[]' and origins != previous_origins)
    save(session_path(url), state)
    reset = bool(allow_retry and changed and applicable_state(url, state) and (remaining(url) or denial_count(url)))
    if reset:
        clear_restriction(url)
    seconds = remaining(url) if allow_retry else None
    message = f'已保存本站 {len(state["cookies"])} 条 Cookie。'
    if reset:
        message += '检测到新的本站状态，已清除之前的失败次数和等待时间，可以立即点击“开始收集网页”。连续被拒绝 3 次后才会暂停 5 分钟。'
    elif seconds:
        message += f'未检测到适用于当前网址的新凭据，原等待时间保留（约 {seconds} 秒）。'
    message += '是否登录有效仍需网站确认，不代表网站已解除访问限制。'
    return {'cookie_count': len(state['cookies']), 'ignored_count': ignored,
            'cooldown_reset': reset, 'cooldown_seconds': seconds, 'message': message}
