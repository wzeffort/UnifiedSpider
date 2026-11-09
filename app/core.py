import csv
import io
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def validate_url(url):
    if urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
        raise ValueError('请输入完整的 http:// 或 https:// 网址')
    return url


def extract(html, url, fields, row_selector=''):
    soup = BeautifulSoup(html, 'html.parser')
    if soup.body is None:
        soup = BeautifulSoup('<html><body>' + html + '</body></html>', 'html.parser')
    rows = soup.select(row_selector) if row_selector else [soup]
    output = []
    for row in rows:
        record = {'来源网址': url}
        for field in fields:
            nodes = row.select(field['selector'])
            values = []
            for node in nodes:
                attr = field.get('attr', 'text')
                value = node.get_text(' ', strip=True) if attr == 'text' else node.get(attr, '')
                if attr in ('href', 'src') and value:
                    value = urljoin(url, value)
                values.append(str(value))
            record[field['name']] = '\n'.join(values)
        output.append(record)
    return output


def csv_bytes(rows):
    out = io.StringIO(newline='')
    keys = list(dict.fromkeys(k for row in rows for k in row)) or ['来源网址']
    writer = csv.DictWriter(out, fieldnames=keys)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
    return out.getvalue().encode('utf-8-sig')


def preview_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script, style, link, iframe, frame, object, embed, base, meta, form, svg, math, audio, video'):
        node.decompose()
    for node in soup.find_all(True):
        for attr in list(node.attrs):
            if attr not in ('id', 'class', 'title', 'alt', 'colspan', 'rowspan'):
                del node.attrs[attr]
    return str(soup)
