import io
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PIL import Image
from content import page_record
from image_assets import collect_images, offline_bundle


class ImageTests(unittest.TestCase):
    def test_image_package(self):
        buffer = io.BytesIO()
        Image.new('RGB', (20, 20), 'blue').save(buffer, format='PNG')
        picture = buffer.getvalue()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == '/photo.png' else 403)
                self.end_headers()
                self.wfile.write(picture if self.path == '/photo.png' else b'Forbidden')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/article'
        try:
            record = page_record(url, '<article><h2>正文</h2><p>段落说明</p><img data-src="/photo.png" src="placeholder.gif" alt="蓝色图片"><img src="/photo.png"><img src="/blocked.png"></article><aside><img src="/ad.png"></aside>', 'test')
            self.assertEqual(len(record['images']), 2)
            self.assertIn('/photo.png', record['markdown'])
            record['notes'].append('部分内容／试读')
            with tempfile.TemporaryDirectory() as tmp:
                collect_images(record, Path(tmp))
                self.assertTrue(record['images'][0]['file'].endswith('.png'))
                self.assertIn('error', record['images'][1])
                bundle = offline_bundle({'pages': [record]}, tmp)
                with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                    self.assertEqual(sum(n.startswith('images/') for n in archive.namelist()), 1)
                    self.assertIn('images/', archive.read('正文.md').decode('utf-8-sig'))
                    self.assertIn('部分内容／试读', archive.read('正文.md').decode('utf-8-sig'))
                    self.assertIn('部分内容／试读', archive.read('打开阅读.html').decode())
                    self.assertIn('images/', archive.read('打开阅读.html').decode())
                    self.assertIn('blocked.png', archive.read('图片说明.txt').decode())
        finally:
            server.shutdown()
            server.server_close()

    def test_offline_html_safety(self):
        page = {'title': '<script>bad</script>', 'url': '', 'markdown': 'text', 'content_html': '<script><b>bad</b></script><p onclick="bad()">safe</p><img src="https://example.com/tracker"><a href="javascript:bad()">link</a>'}
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(offline_bundle({'pages': [page]}, tmp))) as archive:
                html = archive.read('打开阅读.html').decode()
                self.assertNotIn('<script>', html)
                self.assertNotIn('onclick', html)
                self.assertNotIn('javascript:', html)
                self.assertNotIn('src="https:', html)


if __name__ == '__main__':
    unittest.main()
