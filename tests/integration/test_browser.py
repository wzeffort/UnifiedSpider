import json
from pathlib import Path
from playwright.sync_api import sync_playwright


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:18765')
    assert not page.locator('#advanced').get_attribute('open')
    page.locator('#url').fill('https://example.com')
    page.locator('#run').click()
    page.wait_for_function("document.querySelector('#status').textContent.includes('采集完成') || document.querySelector('#status').textContent.includes('采集失败')", timeout=120000)
    assert '采集完成' in page.locator('#status').inner_text(), page.locator('#status').inner_text()
    page.locator('#advanced > summary').click()
    page.frame_locator('#preview').locator('h1').click()
    page.locator('#extract').click()
    page.wait_for_function("document.querySelector('#status').textContent.includes('字段提取已保存')")
    assert 'Example Domain' in page.locator('#table').inner_text()
    for fmt in ('txt', 'csv', 'json', 'md'):
        link = page.locator(f'a[href$="format={fmt}"]').get_attribute('href')
        response = page.request.get('http://127.0.0.1:18765' + link)
        assert response.ok, fmt
        assert 'Example Domain' in response.text(), fmt
        if fmt == 'json':
            page.locator('#downloads summary').click()
        with page.expect_download() as event:
            page.locator(f'a[href$="format={fmt}"]').click()
        download = event.value
        assert download.failure() is None, download.failure()
        assert download.suggested_filename.endswith('.' + fmt), download.suggested_filename
        assert download.path().stat().st_size > 0
        print('Download complete: ' + download.suggested_filename)
    page.locator('#advanced > summary').click()
    page.locator('#downloads summary').click()
    page.screenshot(path=str(Path(__file__).with_name('verified-ui.png')), full_page=True)
    assert not errors, errors
    print(json.dumps({'crawl': 'PASS', 'click_field': 'PASS', 'exports': 'PASS', 'browser_errors': errors}))
    browser.close()
