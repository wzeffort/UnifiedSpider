"""Extract explicit article metadata, keeping uncertain date strings as evidence."""
import re
from datetime import datetime
from bs4 import BeautifulSoup


def extract_metadata(markup):
    soup = BeautifulSoup(markup, 'html.parser')
    author = soup.select_one('meta[name="author"], #js_name, .rich_media_meta_nickname, .author-name, .user-name')
    date = soup.select_one('meta[property="article:published_time"], time[datetime], #publish_time')
    name = (author.get('content') or author.get_text(' ', strip=True)) if author else None
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
