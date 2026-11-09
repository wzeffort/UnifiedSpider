"""Real Chromium extensions with synthetic article DOM; no personal browser data."""
import tempfile
import shutil
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from storage import ROOT
from tests.unit.test_wechat_capture import ARTICLE, CHALLENGE


def run():
    with sync_playwright() as p:
        for addon_name, popup_path in (
            ('browser-extension', 'popup.html'),
            ('CookieEditor-Collector', 'interface/popup/cookie-list.html'),
        ):
            with tempfile.TemporaryDirectory(prefix='current-tab-test-') as tmp:
                addon = Path(tmp) / 'addon'
                shutil.copytree(ROOT / addon_name, addon)
                manifest_path = addon / 'manifest.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                manifest.setdefault('host_permissions', []).append('https://mp.weixin.qq.com/*')
                manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                context = p.chromium.launch_persistent_context(str(Path(tmp) / 'profile'), channel='chromium', headless=True, accept_downloads=True,
                    args=[f'--disable-extensions-except={addon}', f'--load-extension={addon}'])
                try:
                    worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                    extension_id = worker.url.split('/')[2]
                    local = context.new_page()
                    local.goto('http://127.0.0.1:18765/')
                    source = context.new_page()
                    navigations = []
                    source.route('https://mp.weixin.qq.com/**', lambda route: (
                        navigations.append(route.request.url),
                        route.fulfill(content_type='text/html', body=CHALLENGE)))
                    source.goto('https://mp.weixin.qq.com/s/synthetic-current-tab')
                    source_id = worker.evaluate("async()=> (await chrome.tabs.query({})).find(t=>t.url.includes('/s/synthetic-current-tab')).id")
                    popup = context.new_page()
                    popup.goto(f'chrome-extension://{extension_id}/{popup_path}')
                    # Opening a popup as a test tab makes it active. Select the synthetic
                    # source explicitly; all scripting, permission checks and POSTs stay real.
                    popup.evaluate('''id => {
                        const query=chrome.tabs.query.bind(chrome.tabs);
                        chrome.tabs.query=async opts=>opts.active?[await chrome.tabs.get(id)]:query(opts);
                    }''', source_id)
                    popup.locator('#collect-current-tab').click()
                    popup.wait_for_function("() => !document.getElementById('collect-current-tab').disabled")
                    failure = popup.locator('#collect-current-status').inner_text()
                    assert '验证' in failure, failure
                    assert '已保存' not in failure, failure
                    # Model manual verification in the same document, without navigation.
                    source.evaluate('(html)=>{document.open();document.write(html);document.close()}', ARTICLE.replace('</div>', '<p hidden>隐藏内容不能导出</p></div>'))
                    with local.expect_download() as download_event:
                        popup.locator('#collect-current-tab').click()
                    download = download_event.value
                    assert download.failure() is None
                    assert download.suggested_filename.startswith('测试公众号文章_')
                    assert download.suggested_filename.endswith('.md')
                    downloaded = Path(download.path()).read_text(encoding='utf-8-sig')
                    assert '这是验证后已经显示的文章正文' in downloaded
                    assert '推荐列表' not in downloaded
                    popup.wait_for_function("() => !document.getElementById('collect-current-tab').disabled")
                    assert '已发起 Markdown 下载' in popup.locator('#collect-current-status').inner_text()
                    local.wait_for_function("document.getElementById('markdown').textContent.includes('这是验证后已经显示的文章正文')")
                    assert '推荐列表' not in local.locator('#markdown').inner_text()
                    assert '隐藏内容不能导出' not in local.locator('#markdown').inner_text()
                    assert len(navigations) == 1, navigations
                    print(addon_name + ': challenge rejected; current DOM saved; Markdown file downloaded with article filename; no article refetch: PASS')
                finally:
                    context.close()


if __name__ == '__main__':
    run()
