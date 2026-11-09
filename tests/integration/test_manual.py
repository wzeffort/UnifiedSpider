from playwright.sync_api import sync_playwright


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/browser/default?scheme=http', lambda route: route.fulfill(content_type='application/json', body='{"name":"Google Chrome","detected":true,"extension_supported":true,"extension_manager":"chrome://extensions","message":"Default: Google Chrome"}'))
    page.goto('http://127.0.0.1:18765')
    page.wait_for_function("document.getElementById('browserInstallHelp').textContent.includes('检测到 Google Chrome')")
    assert not page.locator('#cookiePaste').is_visible()
    assert not page.locator('#cookiePanel').evaluate('(el)=>el.open')
    page.locator('#cookiePanel > summary').click()
    assert page.locator('#cookiePaste').is_visible()
    assert page.locator('#cookieFile').is_visible()
    assert page.locator('#importCookies').is_visible()
    assert page.locator('#cookiePanel a').count() == 0
    assert page.locator('a[href="/api/browser/cookie-editor.zip"]').count() == 1
    assert '自动获取失败时' in page.locator('#cookiePanel').inner_text()
    assert page.locator('#openDefaultBrowser').count() == 0
    assert page.locator('#autoBrowserCookies').is_checked()
    assert page.locator('#independentBrowser').count() == 0
    assert page.locator('#autoCookies').count() == 0
    assert page.locator('#cookiePanel').evaluate('(el)=>el.tagName==="DETAILS"')
    assert page.locator('#cookiePanel').bounding_box()['y'] < page.locator('#run').bounding_box()['y']
    assert not page.locator('#moreTools').evaluate('(el)=>el.open')
    page.locator('#url').fill('https://example.com/')
    page.locator('#run').click()
    page.wait_for_function("document.getElementById('status').textContent.includes('未连接配套扩展')")
    assert not page.locator('#run').is_disabled()
    page.locator('#moreTools > summary').click()
    assert '网站拒绝' in page.evaluate("readableError('HTTP 403 Forbidden')")
    page.locator('#url').fill('https://www.zhihu.com/question/1933227451481323222/answer/1941421698881681174')
    page.locator('#manual > summary').click()
    page.locator('#manualTitle').fill('手动保存测试')
    page.locator('#manualText').fill('测试正文，不是从知乎自动获取的内容。\n第二段资料。')
    page.locator('#importText').click()
    page.wait_for_function("document.getElementById('manualStatus').textContent.includes('已保存')")
    assert '第二段资料' in page.locator('#table').text_content()
    assert '技术人员' not in page.locator('body').text_content()
    assert page.locator('#downloads > a').first.get_attribute('href').endswith('format=md')
    with page.expect_download() as md_event:
        page.locator('a[href$="format=md"]').click()
    md = md_event.value
    assert md.failure() is None
    assert '# 手动保存测试' in md.path().read_text(encoding='utf-8-sig')
    page.locator('#downloads > details > summary').click()
    with page.expect_download() as event:
        page.locator('a[href$="format=txt"]').click()
    download = event.value
    assert download.failure() is None
    assert download.suggested_filename.startswith('手动保存测试_'), download.suggested_filename
    assert download.suggested_filename.endswith('.txt'), download.suggested_filename
    assert '第二段资料' in download.path().read_text(encoding='utf-8-sig')
    assert not errors, errors
    page.locator('#url').fill('https://cookie-test.example.invalid/')
    page.locator('#sessionPanel').evaluate('(el)=>el.open=true')
    page.locator('#cookieFile').set_input_files({'name': 'fixture.json', 'mimeType': 'application/json', 'buffer': b'[{"name":"test","value":"synthetic-fixture","domain":"cookie-test.example.invalid","path":"/","secure":true}]'})
    assert page.locator('#cookiePanel').is_visible()
    page.locator('#importCookies').click()
    page.wait_for_function("document.getElementById('cookieImportStatus').textContent.includes('已保存本站 1 条')")
    assert 'synthetic-fixture' not in page.locator('body').text_content()
    page.locator('#cookieImportStatus').evaluate('(el)=>el.textContent=""')
    page.locator('#cookiePaste').fill('[{"name":"pasted","value":"paste-fixture-only","domain":"cookie-test.example.invalid","path":"/","secure":true}]')
    page.locator('#importCookies').click()
    page.wait_for_function("document.getElementById('cookieImportStatus').textContent.includes('已保存本站 1 条')")
    assert page.locator('#cookiePaste').input_value() == ''
    page.locator('#cookiePaste').fill('invalid-json-fixture')
    page.locator('#importCookies').click()
    page.wait_for_function("document.getElementById('cookieImportStatus').textContent.includes('不是有效 JSON')")
    assert 'invalid-json-fixture' not in page.locator('#cookieImportStatus').inner_text()
    assert page.locator('#importClipboardCookies').count() == 0
    assert not errors, errors
    print('Friendly 403 message, manual import, TXT download: PASS')
    browser.close()
