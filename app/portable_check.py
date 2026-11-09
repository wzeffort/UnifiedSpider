"""Offline distribution smoke test; all traffic stays on loopback."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import crawl4ai
from playwright.sync_api import sync_playwright
from worker import run

root = Path(sys.executable).resolve().parent
assert Path(crawl4ai.__file__).resolve().is_relative_to(root), 'External developer source is still referenced'
with sync_playwright() as p:
    executable = Path(p.chromium.executable_path).resolve()
    assert executable.is_relative_to(root.parent / 'browsers'), 'External browser referenced'
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content('<h1>Portable browser works</h1>')
    assert page.locator('h1').inner_text() == 'Portable browser works'
    browser.close()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(('<article><h1>Portable test</h1><p>' + 'Offline local fixture content. ' * 20 + '</p></article>').encode())
    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(run({'url': f'http://127.0.0.1:{server.server_port}/', 'engine': 'scrapy'}, tmp))
        assert len(result['pages']) == 1, result.get('failures')
        result = asyncio.run(run({'url': f'http://127.0.0.1:{server.server_port}/', 'engine': 'browser'}))
        assert len(result['pages']) == 1, result.get('failures')
finally:
    server.shutdown()
    server.server_close()

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
process = subprocess.Popen([sys.executable, 'app.py', '--no-browser'], env={**os.environ, 'SPIDER_PORT': str(port)})
try:
    for attempt in range(40):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                assert json.load(response)['app'] == 'UnifiedSpider'
            break
        except OSError:
            if process.poll() is not None:
                raise RuntimeError('Portable server exited')
            time.sleep(.25)
    else:
        raise RuntimeError('Portable server timed out')
finally:
    process.terminate()
    process.wait(timeout=10)
print('PASS: relocated Python, bundled Crawl4AI, bundled Chromium, Scrapy, browser crawl, API startup', flush=True)
