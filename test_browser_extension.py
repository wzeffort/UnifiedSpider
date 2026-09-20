"""Isolated browser + synthetic cookies only; never opens a personal profile."""
import json
import tempfile
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
from storage import ROOT, read, session_path


with tempfile.TemporaryDirectory(prefix='collector-extension-test-') as tmp:
    addon = Path(tmp) / 'extension'
    shutil.copytree(ROOT / 'browser-extension', addon)
    # Test-only pregrant replaces the browser's interactive permission prompt.
    manifest = json.loads((addon / 'manifest.json').read_text(encoding='utf-8'))
    manifest['host_permissions'].append('https://collector-fixture.example.test/*')
    (addon / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(Path(tmp) / 'profile'), channel='chromium', headless=True,
            args=[f'--disable-extensions-except={addon}', f'--load-extension={addon}'])
        try:
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            context.add_cookies([
                {'name': 'auth', 'value': 'synthetic-fixture-only', 'domain': 'collector-fixture.example.test', 'path': '/', 'httpOnly': True, 'secure': True},
                {'name': 'unrelated', 'value': 'never-transfer', 'domain': 'unrelated.example.test', 'path': '/'}])
            page = context.new_page()
            page.goto('http://127.0.0.1:18765/')
            assert page.locator('#autoBrowserCookies').is_checked()
            result = page.evaluate("browserCookieBridge('ping')")
            assert result['status'] == 'connected', result
            assert result['browser'] and result['version'] == '1.3.0', result
            target = 'https://collector-fixture.example.test/article'
            page.locator('#url').fill(target)
            page.wait_for_function("document.getElementById('bridgeStatus').textContent.includes('后台同步本站')")
            assert page.locator('#cookieResult').get_attribute('data-state') == 'saved'
            assert '已成功获取' in page.locator('#cookieResult').inner_text()
            assert 'synthetic-fixture-only' not in page.locator('#cookieResult').inner_text()
            assert page.locator('#authorizeInputCookies').is_hidden()
            assert read(session_path(target))['cookies'][0]['name'] == 'auth'
            quiet = page.evaluate("browserCookieBridge('capture-quiet','https://quiet.example.test/',token)")
            assert quiet['status'] == 'permission'
            assert worker.evaluate("async()=>(await chrome.storage.session.get('pending')).pending") is None
            result = page.evaluate("url=>browserCookieBridge('capture',url,token)", target)
            assert result['status'] == 'saved', result
            assert 'synthetic-fixture-only' not in str(result)
            saved = read(session_path(target))['cookies']
            assert len(saved) == 1 and saved[0]['httpOnly'] and saved[0]['name'] == 'auth'
            context.add_cookies([{'name': 'path-only', 'value': 'synthetic-path', 'domain': 'collector-fixture.example.test', 'path': '/second', 'secure': True}])
            batch = page.evaluate("urls=>browserCookieBridge('capture',urls,token)", [target, 'https://collector-fixture.example.test/second'])
            assert batch['status'] == 'saved', batch
            assert {c['name'] for c in read(session_path(target))['cookies']} == {'auth', 'path-only'}, [(c['name'], c['path']) for c in read(session_path(target))['cookies']]
            blocked = page.evaluate("browserCookieBridge('capture','https://not-granted.example.test/',token)")
            assert blocked['status'] == 'permission', blocked
            pending = worker.evaluate("async()=>(await chrome.storage.session.get('pending')).pending")
            assert pending.get('windowId'), 'Authorization window was not opened'
            page.evaluate("browserCookieBridge('capture','https://not-granted.example.test/',token)")
            assert worker.evaluate("async()=>(await chrome.storage.session.get('pending')).pending.windowId") == pending['windowId'], 'Polling must not open duplicate windows'
            invalid = page.evaluate("browserCookieBridge('capture','https://collector-fixture.example.test/','wrong-token')")
            assert invalid['status'] == 'error', invalid
            empty = page.evaluate("browserCookieBridge('capture','file:///C:/Windows',token)")
            assert empty['status'] == 'unsupported', empty
            # The page's collect handler must wait for synchronization before submitting a job.
            page.locator('#url').fill(target)
            page.evaluate('recentCookieSync.clear()')
            page.evaluate("""() => {const original=window.browserCookieBridge;let calls=0;
                window.browserCookieBridge=(action,...args)=>action==='capture'&&calls++===0?
                    Promise.resolve({status:'permission',message:'Fixture: waiting for permission'}):original(action,...args)}""")
            page.route('**/api/jobs', lambda route: route.fulfill(status=200, content_type='application/json', body='{"id":"fixture-job"}') if route.request.method == 'POST' else route.continue_())
            page.locator('#run').click()
            page.wait_for_function("localStorage.getItem('spider-waiting')==='fixture-job'")
            assert page.locator('#cancelCookieSync').is_hidden()
            page.evaluate("recentCookieSync.clear();window.browserCookieBridge=(action)=>Promise.resolve(action==='ping'?{status:'connected',version:'1.3.0'}:{status:'permission',message:'Fixture permission'})")
            page.locator('#run').evaluate('(button)=>button.disabled=false')
            page.locator('#run').click()
            page.locator('#cancelCookieSync').click()
            page.wait_for_function("document.getElementById('status').textContent.includes('已取消授权等待')")
            # Background refuses requests from foreign origins and non-root paths.
            assert worker.evaluate("async()=>{try{await handle({action:'ping'},{url:'https://example.com/',frameId:0,tab:{id:1}});return false}catch{return true}}")
            print('Extension bridge: real cookie sync, HttpOnly, permission gate, token protection, no secret response, collection integration: PASS')
        finally:
            context.close()
