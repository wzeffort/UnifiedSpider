"""MinerU VLM with local encrypted credentials and resumable image cache."""
import ctypes
import hashlib
import io
import os
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from storage import DATA, read, save

API = 'https://mineru.net/api/v4'
CACHE = DATA / 'mineru-cache'
SECRET = Path(os.environ.get('LOCALAPPDATA', str(DATA))) / 'UnifiedSpider' / 'mineru-token.dpapi'


class Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_char))]


def protect(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('无法读取本机 MinerU 凭据，请重新配置')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def set_token(value):
    SECRET.parent.mkdir(parents=True, exist_ok=True)
    SECRET.write_bytes(protect(value.strip().encode()))


def token():
    if os.environ.get('MINERU_SELF_HOSTED_URL') and os.environ.get('MINERU_MODE')!='hybrid':
        return 'self-hosted'
    return official_token()


def official_token():
    value = os.environ.get('MINERU_API_TOKEN', '').strip()
    token_file=os.environ.get('MINERU_API_TOKEN_FILE')
    if not value and token_file:
        value=Path(token_file).read_text(encoding='utf-8').strip()
    if not value and SECRET.exists():
        value = protect(SECRET.read_bytes(), decrypt=True).decode().strip()
    if not value:
        raise ValueError('尚未配置 MinerU API Token')
    return value


def available():
    try:
        return bool(token())
    except Exception:
        return False


def api(method, path, payload=None):
    try:
        response = requests.request(method, API + path, headers={'Authorization': 'Bearer ' + official_token()},
                                    json=payload, timeout=(8, 20), allow_redirects=False)
        body = response.json()
    except (requests.RequestException, ValueError):
        raise ValueError('MinerU 连接超时或响应异常；请稍后重试，已记录的任务会继续查询') from None
    if response.status_code != 200 or body.get('code') != 0:
        code = body.get('code')
        if code in ('A0202', 'A0211') or response.status_code in (401, 403):
            raise ValueError('MinerU 密钥无效或已过期，请更新本机凭据')
        raise ValueError('MinerU 请求失败（HTTP ' + str(response.status_code) + '），请检查额度或稍后重试')
    return body['data']


def remote(url, method='GET', data=None):
    u = urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password:
        raise ValueError('MinerU 返回了无效的文件地址')
    try:
        with requests.request(method, url, data=data, stream=True, timeout=(8, 30), allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError('MinerU 文件传输失败，请稍后重试')
            result = bytearray()
            for chunk in response.iter_content(65536):
                result.extend(chunk)
                if len(result) > 50 * 1024 * 1024:
                    raise ValueError('MinerU 结果超过 50 MB 上限')
            return bytes(result)
    except requests.RequestException:
        raise ValueError('MinerU 文件传输超时；任务已保留，可重试') from None


def decode_result(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = next((m for m in archive.infolist() if m.filename.split('/')[-1] == 'full.md'), None)
        if member is None or member.file_size > 20 * 1024 * 1024:
            raise ValueError('MinerU 结果缺少有效正文')
        markdown = archive.read(member).decode('utf-8')
    soup = BeautifulSoup(markdown, 'html.parser')
    tables = []
    for table in soup.find_all('table'):
        tables.append([[cell.get_text(' ', strip=True) for cell in row.find_all(['td', 'th'])]
                       for row in table.find_all('tr')])
    return {'engine': 'mineru', 'model': 'vlm', 'text': soup.get_text(' ', strip=True),
            'markdown': markdown, 'tables': tables, 'verified': False}


def recognize(path, timeout=120):
    if os.environ.get('MINERU_SELF_HOSTED_URL'):
        from mineru_selfhost import recognize as local_recognize
        return local_recognize(path, timeout=max(timeout,600))
    return recognize_official(path,timeout)


def recognize_official(path, timeout=120):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE / (digest + '-vlm-v1.json')
    cached = read(cache_path, {})
    if cached.get('result'):
        return cached['result']
    if cached.get('failed') or (not cached.get('uploaded') and cached.get('created') and time.time() - cached['created'] > 23 * 3600):
        cached = {}
    if not cached.get('batch_id'):
        data = api('POST', '/file-urls/batch', {'files': [{'name': 'image' + path.suffix, 'is_ocr': True}],
                   'model_version': 'vlm', 'language': 'ch', 'enable_table': True})
        cached = {'batch_id': data['batch_id'], 'upload_url': data['file_urls'][0], 'created': time.time()}
        save(cache_path, cached)
    if not cached.get('uploaded'):
        if time.time() - cached['created'] > 23 * 3600:
            raise ValueError('MinerU 上传地址已过期，需重新创建图片任务')
        with path.open('rb') as source:
            remote(cached['upload_url'], 'PUT', source)
        cached['uploaded'] = True
        cached.pop('upload_url', None)
        save(cache_path, cached)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = api('GET', '/extract-results/batch/' + cached['batch_id'])
        items = data.get('extract_result', [])
        if items and items[0]['state'] == 'done':
            result = decode_result(remote(items[0]['full_zip_url']))
            result['image_sha256'] = digest
            cached['result'] = result
            save(cache_path, cached)
            return result
        if items and items[0]['state'] == 'failed':
            cached['failed'] = True
            save(cache_path, cached)
            raise ValueError('MinerU 未能解析此图片；点击识别图片可重新提交')
        time.sleep(3)
    raise ValueError('MinerU 仍在排队或识别；稍后重试会继续查询，不重复上传')
