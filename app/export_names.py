import re
from urllib.parse import quote, urlsplit


def export_name(data, status, job_id, extension):
    if extension not in ('txt', 'csv', 'json', 'md', 'zip'):
        raise ValueError('不支持的下载格式')
    first = data['pages'][0]
    title = str(first.get('title') or '').strip()
    if not title or title.startswith(('http://', 'https://')):
        title = urlsplit(first.get('url', '')).hostname or '网页资料'
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '_', title)
    title = re.sub(r'\s+', ' ', title).strip(' .')[:50].rstrip(' .') or '网页资料'
    if re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', title):
        title = '资料_' + title
    timestamp = re.sub(r'\D', '', status.get('created', ''))[:14] or '未记录时间'
    count = len(data['pages'])
    suffix = f'_共{count}页' if count > 1 else ''
    return f'{title}{suffix}_{timestamp}_{job_id[:8]}.{extension}'


def disposition(filename):
    fallback = re.sub(r'[^A-Za-z0-9_.-]', '_', filename)
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
