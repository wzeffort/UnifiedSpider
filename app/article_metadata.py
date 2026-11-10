"""Extract explicit article metadata, keeping uncertain date strings as evidence."""
import re
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlsplit


def extract_account_name(markup, source):
    """Only trust links to the captured account, never an unrelated quoted author."""
    soup = BeautifulSoup(markup, 'html.parser')
    if source.get('platform') == 'wechat':
        node = soup.select_one('#js_name, .rich_media_meta_nickname')
        return node.get_text(' ', strip=True)[:80] if node else None
    owner = str(source.get('owner') or '')
    if source.get('platform') != 'xueqiu' or not owner:
        return None
    for node in soup.select('a[href]'):
        url = urlsplit(node['href'])
        if url.netloc and url.hostname not in ('xueqiu.com', 'www.xueqiu.com'):
            continue
        if url.path.rstrip('/') not in ('/' + owner, '/u/' + owner):
            continue
        name = node.get_text(' ', strip=True).lstrip('@').strip()
        if 1 <= len(name) <= 80 and name not in ('关注', '已关注', '主页', '个人主页', '查看主页'):
            return name
    return None


def extract_metadata(markup, source_url=None):
    soup = BeautifulSoup(markup, 'html.parser')
    author = soup.select_one('meta[name="author"], #js_name, .rich_media_meta_nickname, .author-name, .user-name')
    date = soup.select_one('meta[property="article:published_time"], time[datetime], #publish_time')
    name = (author.get('content') or author.get_text(' ', strip=True)) if author else None
    page = urlsplit(source_url or '')
    if page.hostname in ('xueqiu.com','www.xueqiu.com'):
        identity = re.fullmatch(r'/(\d+)/(\d+)/?',page.path)
        name = extract_account_name(markup, {'platform':'xueqiu','owner':identity[1]}) if identity else None
    raw = (date.get('content') or date.get('datetime') or date.get_text(' ', strip=True)) if date else None
    normalized = None
    if raw:
        match = re.fullmatch(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?', raw.strip())
        try:
            normalized = datetime(*map(int, match.groups())).date().isoformat() if match else datetime.fromisoformat(raw.strip().replace('Z', '+00:00')).isoformat()
        except ValueError:
            pass
    return {'author_name': name[:200] if name else None, 'published_at': normalized,
            'published_at_raw': raw, 'metadata_source': 'page-explicit-fields'}
