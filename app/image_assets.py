"""Bounded image collection and offline export; no credentials sent to CDNs."""
import hashlib
import html
import io
import time
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return '.gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return '.webp'
    raise ValueError('不是支持的图片格式（支持 JPG、PNG、GIF、WebP）')


def collect_images(page, folder):
    if not folder:
        return
    target = Path(folder) / 'images'
    target.mkdir(exist_ok=True)
    budget = max(0, 100 * 1024 * 1024 - sum(p.stat().st_size for p in target.iterdir() if p.is_file()))
    deadline = time.monotonic() + 60
    with requests.Session() as client:
        for index, item in enumerate(page.get('images', [])):
            try:
                if index >= 40 or budget <= 0 or time.monotonic() >= deadline:
                    raise ValueError('达到本次图片下载上限')
                name = hashlib.sha256(item['url'].encode()).hexdigest()
                cached = next(target.glob(name + '.*'), None)
                if cached:
                    item['file'] = 'images/' + cached.name
                    continue
                with client.get(item['url'], headers={'Referer': page['url']}, timeout=(5, 8), stream=True) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > min(8 * 1024 * 1024, budget) or time.monotonic() >= deadline:
                            raise ValueError('图片过大或下载超时')
                        chunks.append(chunk)
                    data = b''.join(chunks)
                path = target / (name + image_extension(data))
                path.write_bytes(data)
                item['file'] = 'images/' + path.name
                budget -= size
            except Exception as exc:
                item['error'] = '图片未保存：' + str(exc)[:180]
    failed = sum('file' not in i for i in page.get('images', []))
    if failed:
        page.setdefault('notes', []).append(f'{failed} 张图片未下载，文档保留原图链接。')


def offline_bundle(data, folder):
    output = io.BytesIO()
    documents, rendered, warnings, added = [], [], [], set()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for page in data['pages']:
            markdown = page['markdown']
            soup = BeautifulSoup(page.get('content_html') or '<pre>' + html.escape(page.get('text', markdown)) + '</pre>', 'html.parser')
            mapping = {}
            for item in page.get('images', []):
                relative = item.get('file', '')
                file = (Path(folder) / relative).resolve()
                if relative and file.parent == (Path(folder) / 'images').resolve() and file.is_file():
                    mapping[item['url']] = relative
                    if relative not in added:
                        archive.write(file, relative)
                        added.add(relative)
                    markdown = markdown.replace(item['url'], relative)
                else:
                    warnings.append(item['url'] + '：' + item.get('error', '未下载，请重新采集'))
            allowed = {'p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'pre', 'code', 'blockquote', 'strong', 'b', 'em', 'i', 'br', 'hr', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'a', 'img', 'figure', 'figcaption', 'span'}
            for node in list(soup.find_all(True)):
                if node.name is None:
                    continue
                if node.name in ('script', 'style', 'iframe', 'object', 'embed'):
                    node.decompose()
                elif node.name not in allowed:
                    node.unwrap()
                else:
                    attrs = dict(node.attrs)
                    node.attrs = {}
                    if node.name == 'img':
                        if attrs.get('src') in mapping:
                            node['src'] = mapping[attrs['src']]
                            node['alt'] = attrs.get('alt', '')
                        else:
                            node.replace_with('[图片未下载，原链接见文档和图片说明]')
                    elif node.name == 'a' and str(attrs.get('href', '')).startswith(('http://', 'https://')):
                        node['href'] = attrs['href']
            title = page.get('title', '网页资料')
            notice = '；'.join(page.get('notes', []))
            documents.append('# ' + title + '\n\n来源：' + page['url'] + ('\n\n说明：' + notice if notice else '') + '\n\n' + markdown)
            rendered.append('<h1>' + html.escape(title) + '</h1><p>来源：' + html.escape(page['url']) + '</p><p>' + html.escape(notice) + '</p>' + str(soup))
        archive.writestr('正文.md', '\n\n---\n\n'.join(documents).encode('utf-8-sig'))
        archive.writestr('打开阅读.html', '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'"><title>网页资料</title><style>body{max-width:900px;margin:40px auto;padding:24px;font:17px/1.8 system-ui}img{max-width:100%;height:auto}pre{white-space:pre-wrap;background:#f3f5f7;padding:16px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:8px}</style>' + '<hr>'.join(rendered))
        archive.writestr('图片说明.txt', '请先解压全部文件，再双击“打开阅读.html”。\n正文.md 和 images 文件夹请放在一起。\n已保存图片：' + str(len(added)) + '\n' + '\n'.join(warnings))
    return output.getvalue()
