"""Exercise the modified Cookie-Editor with synthetic cookies in an isolated profile."""
import tempfile
from playwright.sync_api import sync_playwright
from storage import ROOT, session_path, read
from cookie_editor_package import addon_root

addon = addon_root()
target = 'https://cookie-editor-fixture.example.test/article'
with tempfile.TemporaryDirectory(prefix='cookie-editor-bridge-test-') as tmp, sync_playwright() as p:
    context = p.chromium.launch_persistent_context(tmp, channel='chromium', headless=True,
        args=[f'--disable-extensions-except={addon}',f'--load-extension={addon}'])
    try:
        context.add_cookies([
            {'name':'fixture_auth','value':'synthetic-only','domain':'cookie-editor-fixture.example.test','path':'/','secure':True,'httpOnly':True},
            {'name':'unrelated','value':'never-send','domain':'unrelated.example.test','path':'/','secure':True}])
        page=context.new_page()
        page.goto('http://127.0.0.1:18765/')
        result=page.evaluate("browserCookieBridge('ping')")
        assert result['provider']=='cookie-editor',result
        with context.expect_page() as popup_event:
            page.locator('#url').fill(target)
        popup=popup_event.value
        popup.wait_for_load_state()
        assert 'cookie-editor-fixture.example.test' in popup.locator('#site').inner_text()
        assert not page.locator('#cookieResult').get_attribute('data-state')=='saved'
        # A failed local save must leave the authorization window available.
        page.evaluate("""() => {window.originalBridge=window.browserCookieBridge;
            window.browserCookieBridge=(action,url,token)=>window.originalBridge(action,url,action==='capture-quiet'?'invalid-token':token)}""")
        popup.locator('#allow').click()
        page.wait_for_function("document.getElementById('cookieResult').dataset.state==='error'")
        assert not popup.is_closed(), 'Failed save must not close the authorization window'
        page.evaluate("window.browserCookieBridge=window.originalBridge;recentCookieSync.clear();prefetchInputCookies()")
        page.wait_for_function("document.getElementById('cookieResult').dataset.state==='saved'")
        assert popup.is_closed(), 'Successful save must close only the authorization popup'
        saved=read(session_path(target))['cookies']
        assert len(saved)==1 and saved[0]['name']=='fixture_auth' and saved[0]['httpOnly']
        assert 'synthetic-only' not in page.locator('body').text_content()
        count=len(context.pages)
        report=page.evaluate("url=>browserCookieBridge('capture-quiet',url,token)",target)
        assert report['status']=='saved' and len(context.pages)==count
        worker=context.service_workers[0]
        worker.evaluate("chrome.storage.local.remove('collector-approved:https://cookie-editor-fixture.example.test')")
        denied=page.evaluate("url=>browserCookieBridge('capture-quiet',url,token)",target)
        assert denied['status']=='permission'
        extension_id=worker.url.split('/')[2]
        original=context.new_page()
        original.goto(f'chrome-extension://{extension_id}/interface/popup/cookie-list.html')
        original.wait_for_load_state()
        assert original.locator('body').inner_text().strip()
        print('Cookie-Editor fork: automatic authorization window, real consent click, auto sync, scoped HttpOnly, consent reuse/revoke, original popup loads: PASS')
    finally:
        context.close()
