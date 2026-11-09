"""Controlled local fixture: no external membership accounts or purchases."""
import asyncio
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from content import classify
from export_names import export_name, disposition
from storage import save
from worker import run


class Tests(unittest.TestCase):
    def test_names(self):
        data = {'pages': [{'title': '老板资料:季度/报告', 'url': 'https://example.com'}]}
        for fmt in ('txt', 'csv', 'json', 'md'):
            name = export_name(data, {'created': '2026-09-15 12:34:56'}, 'abcdef12-1234', fmt)
            self.assertEqual(name, '老板资料_季度_报告_20260915123456_abcdef12.' + fmt)
            self.assertIn("filename*=UTF-8''", disposition(name))
        data['pages'] *= 2
        self.assertIn('_共2页_', export_name(data, {}, '12345678', 'txt'))

    def test_detection(self):
        self.assertEqual(classify('<article><meta itemprop="isAccessibleForFree" content="false">' + '授权后全文可见。' * 30 + '</article>'), 'ok')
        self.assertEqual(classify('<article><div class="paywall">会员专享，解锁全文</div></article>'), 'paywall')
        self.assertEqual(classify('<article>' + '这篇公开文章介绍会员制度。' * 20 + '</article>'), 'ok')
        self.assertEqual(classify('<article>' + '公开正文。' * 30 + '<div hidden class="paywall">解锁全文</div></article>'), 'ok')

    def test_authorized_member_content(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                html = '<title>会员测试</title><article>'
                if 'member=test-only' in self.headers.get('Cookie', ''):
                    html += '已授权的完整会员正文。' * 30
                else:
                    html += '<p>' + '公开可见的试读内容。' * 10 + '</p><div class="paywall">会员专享，请解锁全文</div>'
                body = (html + '</article>').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/member'
        try:
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / 'state.json'
                with patch('worker.session_path', return_value=state), patch('worker.applicable_state', return_value=False):
                    result = asyncio.run(run({'url': url, 'engine': 'scrapy'}))
                self.assertEqual(result['failures'], [])
                self.assertTrue(result['pages'][0]['partial_content'])
                self.assertIn('试读', result['pages'][0]['text'])
                self.assertNotIn('skipped', result)
                save(state, {'cookies': [{'name': 'member', 'value': 'test-only', 'domain': '127.0.0.1', 'path': '/', 'expires': -1, 'httpOnly': False, 'secure': False, 'sameSite': 'Lax'}], 'origins': []})
                with patch('worker.session_path', return_value=state), patch('worker.applicable_state', return_value=True):
                    result = asyncio.run(run({'url': url, 'engine': 'auto', 'use_session': True}))
                self.assertEqual(len(result['pages']), 1, result)
                self.assertIn('已授权的完整会员正文', result['pages'][0]['text'])
                self.assertEqual(result['pages'][0]['access_mode'], 'saved-state')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
