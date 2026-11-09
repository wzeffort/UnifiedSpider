import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from worker import run


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        index = '2' if self.path == '/two' else '1'
        text = 'This is a local catalog fixture for testing extraction and pagination with a real browser. ' * 12
        html = f'<html><head><title>Page {index}</title></head><body><article class="item"><h2>Item {index}</h2><p>{text}</p></article><a class="next" href="/two">Next</a></body></html>'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    for mode in ('next', 'site'):
        result = asyncio.run(run({'url': f'http://127.0.0.1:{server.server_port}/', 'limit': 2,
            'fields': [{'name': 'title', 'selector': 'h2'}], 'row': '.item',
            'next': '.next' if mode == 'next' else '', 'site': mode == 'site'}))
        assert len(result['pages']) == 2, result
        assert [row['title'] for row in result['rows']] == ['Item 1', 'Item 2']
        print(mode + ': PASS')
finally:
    server.shutdown()
