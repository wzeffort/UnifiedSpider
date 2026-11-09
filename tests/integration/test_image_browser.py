"""Actual job, browser download, and offline rendering against a local fixture."""
import io
import tempfile
import threading
import zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image
from playwright.sync_api import sync_playwright

buf = io.BytesIO()
Image.new('RGB', (80, 60), '#087f8c').save(buf, format='PNG')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'image/png' if self.path == '/photo.png' else 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(buf.getvalue() if self.path == '/photo.png' else ('<title>图文下载测试</title><article><h1>图文下载测试</h1><p>' + '公开测试正文，验证图片离线阅读。' * 20 + '</p><img src="/photo.png" alt="测试照片"></article>').encode())
    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:18765/')
        page.locator('#url').fill(f'http://127.0.0.1:{server.server_port}/article')
        page.locator('#run').click()
        page.wait_for_function("document.getElementById('status').textContent.includes('采集完成')", timeout=60000)
        assert '已保存 1 张' in page.locator('#quality').inner_text()
        with page.expect_download() as event:
            page.locator('a[href$="format=zip"]').click()
        download = event.value
        assert download.failure() is None
        assert download.suggested_filename.startswith('图文下载测试_')
        with zipfile.ZipFile(download.path()) as archive:
            archive.extractall(tmp)  # Locally generated fixture archive only.
        page.goto((Path(tmp) / '打开阅读.html').as_uri())
        page.wait_for_function("document.images.length === 1 && document.images[0].naturalWidth === 80")
        assert not errors, errors
        print('Job image collection, ZIP download, offline HTML image rendering: PASS')
        browser.close()
finally:
    server.shutdown()
    server.server_close()
