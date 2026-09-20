"""Use OS URL association, never inspect personal browser profiles."""
import os
import sys
import webbrowser
from urllib.parse import urlsplit
from core import validate_url


def association(scheme):
    import winreg
    key = rf'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
        return winreg.QueryValueEx(handle, 'ProgId')[0]


def browser_info(scheme='https'):
    if scheme not in ('http', 'https'):
        raise ValueError('仅支持网页地址')
    name = '系统默认浏览器'
    detected = False
    family, manager = 'unknown', ''
    if sys.platform == 'win32':
        try:
            progid = association(scheme).lower()
            for prefix, label, kind, settings in (
                    ('msedge', 'Microsoft Edge', 'edge', 'edge://extensions'),
                    ('chrome', 'Google Chrome', 'chrome', 'chrome://extensions'),
                    ('firefox', 'Mozilla Firefox', 'firefox', ''),
                    ('brave', 'Brave', 'chromium', 'brave://extensions')):
                if progid.startswith(prefix):
                    name, detected = label, True
                    family, manager = kind, settings
                    break
        except OSError:
            pass
    return {'name': name, 'detected': detected, 'family': family, 'extension_manager': manager,
            'extension_supported': family in ('edge', 'chrome'),
            'message': f'系统默认浏览器：{name}。后台同步来自实际连接扩展的浏览器个人资料，不跨浏览器读取。'}


def open_default(url):
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise ValueError('请输入有效的网页地址')
    url = validate_url(url.strip())
    if urlsplit(url).username is not None or urlsplit(url).password is not None:
        raise ValueError('请使用不含账号密码的网页地址')
    if sys.platform == 'win32':
        os.startfile(url)  # ShellExecute respects the user's HTTP/HTTPS association.
    elif not webbrowser.open(url, new=2):
        raise ValueError('未能打开默认浏览器，请手动复制网址打开')
    return {'ok': True, 'message': '已请求系统默认浏览器打开网页；配套扩展连接后可在采集时后台同步本站 Cookie。'}
