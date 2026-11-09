"""Use synthetic Xueqiu pages in isolated Chromium; exercise the real queue and ZIP."""
import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from storage import ROOT, session_path
from tests.unit.test_author_batch import LIST, POST
from tests.unit.test_wechat_capture import CHALLENGE


POST = '<meta name="author" content="元数据测试作者"><meta property="article:published_time" content="2026-11-05T09:00:00+08:00">' + POST

with sync_playwright() as p:
    for name in ('browser-extension', 'CookieEditor-Collector'):
        owner = str(time.time_ns())
        with tempfile.TemporaryDirectory(prefix='author-extension-') as tmp:
            addon = Path(tmp) / 'addon'
            shutil.copytree(ROOT / name, addon)
            manifest_path = addon / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['host_permissions'].append('https://xueqiu.com/*')
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            context = p.chromium.launch_persistent_context(str(Path(tmp) / 'profile'), channel='chromium', headless=True,
                accept_downloads=True, args=[f'--disable-extensions-except={addon}', f'--load-extension={addon}'])
            original_settings = None
            cookie_file = session_path("https://xueqiu.com")
            original_cookie_state = cookie_file.read_bytes() if cookie_file.exists() else None
            try:
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                if name == 'CookieEditor-Collector':
                    context.add_cookies([{'name':'collector_test','value':'fixture','url':'https://xueqiu.com'}])
                list_html = LIST + '<a href="/123/1">第一篇</a><a href="/123/1?dup=1">重复</a><a href="/123/2">第二篇</a><a href="/999/3">其他作者</a>'.replace('/123/', '/'+owner+'/')
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('http://127.0.0.1:18765/', 'chrome-extension://')) else route.abort())
                context.route('https://xueqiu.com/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=(
                    list_html if '/u/'+owner in route.request.url else CHALLENGE if route.request.url.endswith('/'+owner+'/1') else POST)))
                local = context.new_page()
                downloads = []
                local.on('download', lambda download: downloads.append(download))
                local.goto('http://127.0.0.1:18765/')
                local.locator('#authorSettings > summary').click()
                original_settings = local.evaluate("api('/api/download-settings')")
                local.evaluate("config=>api('/api/download-settings',{...config,mode:'browser'})", original_settings)
                output = Path(tmp) / 'RAG 本机资料'
                if name == 'CookieEditor-Collector':
                    local.locator('#authorSaveFolder').fill(str(output))
                    local.locator('#authorApplyFolder').click()
                    local.wait_for_function("value=>document.getElementById('authorSaveStatus').textContent.includes('已应用本机保存目录：'+value)", arg=str(output))
                local.evaluate("async()=>{for(const task of await api('/api/authors'))if(task.source.owner==='123'&&task.state!=='finished')await api('/api/authors/'+task.id+'/control',{action:'pause'})}")
                local.locator('#authorUrls').fill('https://xueqiu.com/u/'+owner)
                local.locator('#authorLimit').fill('2')
                if name == 'CookieEditor-Collector':
                    with context.expect_page() as permission_window:
                        local.locator('#authorStart').click()
                    permission_page = permission_window.value
                    permission_page.wait_for_url('**/collector-authorize.html?request=*')
                    with permission_page.expect_event('close'):
                        permission_page.locator('#allow').click()
                    print('Cookie-Editor: missing consent automatically opened popup; approval synced cookies and resumed: PASS', flush=True)
                else:
                    local.locator('#authorStart').click()
                row = local.locator('#authorTasks .job').first
                try:
                    row.get_by_text('等待人工处理', exact=False).wait_for(timeout=45000)
                except Exception:
                    print(local.locator('#authorStatus').inner_text())
                    print(row.inner_text())
                    print('TAB URLS:', [page.url for page in context.pages])
                    print('EXT TABS:', worker.evaluate('async()=> (await chrome.tabs.query({})).map(t=>({id:t.id,url:t.url,pendingUrl:t.pendingUrl,status:t.status}))'))
                    raise
                assert '正文已入库 0' in row.inner_text()
                source = next(page for page in context.pages if page.url == 'https://xueqiu.com/'+owner+'/1')
                source.evaluate('(html)=>{document.open();document.write(html);document.close()}', POST)
                task_id = row.get_attribute('data-task-id')
                row = local.locator('[data-task-id="'+task_id+'"]')
                row.get_by_role('button', name='继续', exact=True).click()
                local.wait_for_function("async id=>(await api('/api/authors/'+id)).auto_state==='done'", arg=task_id, timeout=45000)
                local.wait_for_timeout(6000)
                local.locator('#authorHistory > summary').click()
                row.locator(':scope > summary').click()
                row.get_by_text('详情与其他操作',exact=True).click()
                assert '正文已入库 2' in row.inner_text(), row.inner_text()
                assert len(context.pages) == 3, 'Only the initial blank page, local tool and one worker tab may exist'
                assert len(downloads) == (0 if name == 'CookieEditor-Collector' else 1)
                if name == 'CookieEditor-Collector':
                    assert len(list(output.rglob('export.json'))) == 1, 'Folder mode must automatically save at completion'
                with local.expect_download() as event:
                    row.get_by_role('link', name='下载资料包（Markdown＋JSONL）').click()
                with zipfile.ZipFile(event.value.path()) as archive:
                    markdown = [n for n in archive.namelist() if n.endswith('.md')]
                    assert len(markdown) == 2
                    assert all('历史帖子正文' in archive.read(n).decode('utf-8-sig') for n in markdown)
                    checklist = json.loads(archive.read('采集清单.json'))
                    assert len(checklist['discovered']) == 2
                    assert len(checklist['saved']) == 2
                    assert checklist['remaining'] == []
                    docs = [json.loads(line) for line in archive.read('documents.jsonl').decode('utf-8').splitlines()]
                    assert len(docs) == 2
                    assert all(doc['author_id'] == owner and doc['text'] for doc in docs)
                    assert all(doc['author_name'] == '元数据测试作者' and doc['published_at'] == '2026-11-05T09:00:00+08:00' for doc in docs)
                local.locator('#authorSaveFolder').fill(str(output))
                local.locator('#authorApplyFolder').click()
                local.wait_for_function("value=>document.getElementById('authorSaveStatus').textContent.includes('已应用本机保存目录：'+value)", arg=str(output))
                row.get_by_role('button', name='保存到本机目录', exact=True).click()
                local.wait_for_function("value=>document.getElementById('authorTasks').textContent.includes('上次导出目录：'+value)", arg=str(output))
                ready = list(output.rglob('export.json'))
                assert len(ready) == 1
                exported = json.loads(ready[0].read_text(encoding='utf-8'))
                assert exported['ready'] and exported['documents_count'] == 2
                assert len(Path(exported['documents_file']).read_text(encoding='utf-8').splitlines()) == 2
                awaitable = local.evaluate('''async()=>{
                    const next=await api('/api/authors',{url:'https://xueqiu.com/u/123',limit:2});
                    await api('/api/authors/'+next.id+'/control',{action:'resume'});
                    const reply=await browserCookieBridge('author-step',next.id,token);
                    await api('/api/authors/'+next.id+'/control',{action:'pause'});
                    return reply.status;
                }'''.replace('/u/123', '/u/'+owner))
                assert awaitable == 'loading'
                assert len(context.pages) == 3, 'A second author task must reuse the same worker tab'
                print(name + ': one worker across tasks; verification/resume; ZIP/JSONL; frontend path selection -> real folder export: PASS')
            finally:
                if original_settings is not None:
                    local.evaluate("config=>api('/api/download-settings',config)", original_settings)
                context.close()
                if cookie_file.exists():
                    state = json.loads(cookie_file.read_text(encoding='utf-8'))
                    if state.get('cookies') and all(c.get('name') == 'collector_test' and c.get('value') == 'fixture' for c in state['cookies']):
                        if original_cookie_state is None:
                            cookie_file.unlink()
                        else:
                            cookie_file.write_bytes(original_cookie_state)
