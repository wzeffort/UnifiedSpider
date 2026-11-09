"""Exercise the shipped scanner against deterministic pagination/scroll/slow-load DOM."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import author_batch as batch


class Discovery(unittest.TestCase):
    def test_real_scanner_pagination_scrolling_and_slow_load(self):
        code = Path('browser-extension/author-batch.js').read_text(encoding='utf-8')
        self.assertEqual(code, Path('CookieEditor-Collector/author-batch.js').read_text(encoding='utf-8'))
        start = code.index('func:phase=>{') + len('func:phase=>{')
        scanner = '(phase)=>{' + code[start:code.index('  }});', start)] + '}'
        with tempfile.TemporaryDirectory() as temp, patch('author_batch.job_folder', side_effect=lambda id: Path(temp) / id), patch('author_batch.time.time', return_value=2_000_000_000) as clock, sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            def links(start, end):
                return ''.join(f'<a href="https://xueqiu.com/123/{i}">历史文章正文内容标题{i}</a>' for i in range(start, end))
            def report(state):
                clock.return_value += 4
                payload = page.evaluate(scanner, 'scan')
                return batch.report(state['id'], {**payload, 'revision': state['revision']})
            page.route('https://xueqiu.com/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=(
                '<title>作者历史</title>' + links(27, 53) + '<button class="pagination__next disabled">下一页</button>' if '?page=2' in route.request.url else
                '<title>作者历史</title>' + links(1, 27) + '<a rel="next" href="/u/123?page=2">下一页</a>')))
            page.goto('https://xueqiu.com/u/123')
            state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 500})['id'], 'resume')
            state = report(state)
            page.wait_for_url('**?page=2')
            state = report(state)
            state = report(state)
            self.assertEqual(state['discovered'], 52)
            self.assertEqual(state['phase'], 'capture')

            page.goto('https://xueqiu.com/u/123')
            page.set_content('<title>作者历史</title><div id="feed" style="height:200px;overflow:auto">' + links(1, 27) + '<div style="height:12000px"></div><div class="no-more">没有更多了</div></div>')
            state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123'})['id'], 'resume')
            for _ in range(8):
                state = report(state)
            self.assertEqual(state['phase'], 'scan')
            self.assertEqual(state['state'], 'running')
            page.evaluate("document.getElementById('feed').scrollTop=20000")
            state = report(state)
            state = report(state)
            self.assertEqual(state['phase'], 'capture')

            page.set_content('<title>作者历史</title><main id="posts">' + links(1, 27) + '</main><button id="more">加载更多</button><div class="loading" hidden>加载中</div>')
            page.evaluate("""()=>{document.getElementById('more').onclick=()=>{
              document.getElementById('more').disabled=true;
              document.querySelector('.loading').hidden=false;
              setTimeout(()=>{document.querySelector('.loading').hidden=true;document.getElementById('more').remove();
                document.getElementById('posts').insertAdjacentHTML('beforeend','<a href="https://xueqiu.com/123/27">新文章正文</a><div class="no-more">没有更多了</div>');},700);
            }}""")
            state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123'})['id'], 'resume')
            state = report(state)
            state = report(state)
            self.assertEqual(state['phase'], 'scan')
            page.wait_for_selector('.no-more')
            state = report(state)
            state = report(state)
            self.assertEqual(state['discovered'], 27)
            self.assertEqual(state['phase'], 'capture')
            browser.close()


if __name__ == '__main__':
    unittest.main()
