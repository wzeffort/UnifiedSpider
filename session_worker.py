"""User-controlled visible browser; confirmation is sent from the local UI."""
import sys
import time
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from content import page_record, classify
from storage import read, save, session_path, profile_path
from site_access import clear_restriction
from jobs import job_folder
from cookie_state import store_state
from browser_state_capture import StateCapture, page_ready


def run(folder, headless=False):
    config = read(folder / 'session-config.json')
    url = config['url']
    state = session_path(url)
    with sync_playwright() as p:
        profile = profile_path(url)
        first_profile = not profile.exists()
        profile.mkdir(parents=True, exist_ok=True)
        context = p.chromium.launch_persistent_context(str(profile), headless=headless)
        if state.exists():
            context.set_storage_state(str(state))
        navigation_status = {}
        def track_response(response):
            try:
                if response.request.is_navigation_request() and response.frame == response.frame.page.main_frame:
                    navigation_status[response.frame.page] = response.status
            except Exception:
                pass
        context.on('response', track_response)
        def track_failure(request):
            try:
                if request.is_navigation_request() and request.frame == request.frame.page.main_frame:
                    navigation_status[request.frame.page] = 0
            except Exception:
                pass
        context.on('requestfailed', track_failure)
        page = context.new_page()
        opening_message = '这是工具的独立浏览器，不含 Edge 等日常浏览器的登录状态。请自行登录或验证，看到正文后保存。'
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
        except Exception:
            navigation_status[page] = 0
            opening_message = '独立浏览器打开网页失败或超时，未自动保存状态。建议用上方“系统默认浏览器”打开，在已登录的浏览器中导出 Cookie 后粘贴导入。'
        save(folder / 'session-status.json', {'state': 'waiting', 'message': opening_message})
        deadline = time.monotonic() + 900
        capture = StateCapture(url) if config.get('auto_save') else None
        next_capture = 0
        while time.monotonic() < deadline:
            if capture and time.monotonic() >= next_capture:
                next_capture = time.monotonic() + 3
                try:
                    live = context.pages[-1] if context.pages else page
                    ready = page_ready(url, live.url, navigation_status.get(live))
                    report = capture.capture(context) if ready else None
                    if report:
                        save(folder / 'session-status.json', {'state': 'waiting', **report})
                    elif not ready:
                        save(folder / 'session-status.json', {'state': 'waiting', 'message': '当前页面未成功打开本站，自动保存已暂停。请用系统默认浏览器查看，或在此窗口重新打开网页。'})
                except Exception:
                    save(folder / 'session-status.json', {'state': 'waiting', 'message': '暂未保存本站状态，可以继续登录，或改用粘贴 Cookie 导入。'})
            if (folder / 'session-state').exists():
                (folder / 'session-state').unlink()
                try:
                    report = store_state(url, context.storage_state(indexed_db=True), allow_retry=True)
                    save(folder / 'session-status.json', {'state': 'waiting', **report})
                except Exception:
                    save(folder / 'session-status.json', {'state': 'waiting', 'message': '尚未获取到本站状态。请在操作浏览器中自行登录后再保存，或使用下方导入方式。'})
            if (folder / 'session-cancel').exists():
                save(folder / 'session-status.json', {'state': 'closed', 'message': '浏览器已关闭'})
                context.close()
                return
            if (folder / 'session-confirm').exists():
                (folder / 'session-confirm').unlink()
                try:
                    live = context.pages[-1] if context.pages else page
                    if urlsplit(live.url).netloc != urlsplit(url).netloc:
                        raise ValueError('请回到最初的网站正文页面后再保存')
                    html = live.content()
                    reason = classify(html, navigation_status.get(live, 200))
                    if reason != 'ok' and not (reason == 'paywall' and navigation_status.get(live, 200) == 200):
                        # Saving an already open page is not a new network request.
                        raise ValueError('当前页面可能仍是登录或验证页，请完成后再保存：' + reason)
                    try:
                        store_state(url, context.storage_state(indexed_db=True))
                    except ValueError:
                        pass  # Public pages need not set cookies; preserve any previous state.
                    clear_restriction(url)
                    record = page_record(live.url, html, 'manual-browser')
                    from image_assets import collect_images
                    collect_images(record, folder)
                    save(folder / 'result.json', {'pages': [record], 'rows': [{'来源网址': record['url'], '标题': record['title'], '正文': record['text']}], 'failures': []})
                    save(folder / 'status.json', {'id': folder.name, 'url': live.url, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'status': 'done', 'pages': 1, 'rows': 1, 'source': 'manual-browser'})
                    save(folder / 'session-status.json', {'state': 'saved', 'message': '当前页面和本站登录状态已保存，可下载结果。'})
                    context.close()
                    return
                except Exception as exc:
                    save(folder / 'session-status.json', {'state': 'waiting', 'message': str(exc)})
            page.wait_for_timeout(300)
        save(folder / 'session-status.json', {'state': 'closed', 'message': '超过 15 分钟未确认，浏览器已关闭'})
        context.close()


if __name__ == '__main__':
    folder = job_folder(sys.argv[1])
    try:
        run(folder)
    except Exception as exc:
        save(folder / 'session-status.json', {'state': 'closed', 'message': str(exc)})
