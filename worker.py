"""Isolated job worker; checkpoint after every page, never discard successful pages."""
import asyncio
import json
import sys
from pathlib import Path
from collections import deque
from contextlib import AsyncExitStack

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from core import extract, validate_url
from content import classify, page_record, discover
from storage import read, save, session_path
from site_access import applicable_state, needs_confirmation, remaining, record_denial, clear_restriction, denial_count

ROOT = Path(__file__).resolve().parent


async def run(config, folder=None):
    folder = Path(folder) if folder else None
    previous = read(folder / 'result.json', {}) if folder else {}
    pages = previous.get('pages', [])
    rows = previous.get('rows', [])
    failures = []
    successful = {p['url'] for p in pages}
    queue = deque(config.get('urls') or [config['url']])
    # Re-discover links from saved pages when resuming interrupted jobs.
    for page in pages:
        queue.extend(discover(page['html'], page['url'], config))
    seen = set()
    attempted = 0
    limit = config.get('limit', 1)
    async with AsyncExitStack() as stack:
        browser = None

        def checkpoint(state='running', current=''):
            result = {'pages': pages, 'rows': rows, 'failures': failures}
            if folder:
                save(folder / 'result.json', result)
                save(folder / 'progress.json', {'state': state, 'current': current, 'pages': len(pages),
                     'failed_pages': len(failures), 'pending': len(queue), 'attempted': attempted})
            return result

        while queue and attempted < limit and len(pages) < limit:
            if folder and (folder / 'cancel').exists():
                break
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if url in successful:
                continue
            attempted += 1
            checkpoint(current=url)
            engine = config.get('engine', 'auto')
            state = session_path(url)
            with_state = applicable_state(url) and config.get('use_session', True)
            mode = 'browser' if with_state else engine
            html, code, used = '', 200, 'scrapy'
            try:
                if remaining(url):
                    raise RuntimeError('cooldown')
                if needs_confirmation(url, config.get('use_session', True)):
                    raise RuntimeError('session_required')
                if mode in ('auto', 'scrapy'):
                    import tempfile
                    with tempfile.TemporaryDirectory(prefix='unified-fetch-') as temp:
                        response_file = Path(temp) / 'response.json'
                        proc = await asyncio.create_subprocess_exec(
                            sys.executable, str(ROOT / 'scrapy_fetch.py'),
                            json.dumps({'url': url}), str(response_file))
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=100)
                        except asyncio.TimeoutError:
                            proc.kill()
                            await proc.wait()
                            raise RuntimeError('Scrapy 请求超时')
                        response = read(response_file, {})
                    if response.get('error'):
                        if mode == 'scrapy':
                            raise RuntimeError(response['error'])
                        mode = 'browser'
                    else:
                        html, code = response.get('html', ''), response.get('status', 200)
                        reason = classify(html, code)
                        # Never hammer denial responses with additional automated browsers.
                        if reason in ('blocked', 'verification', 'login', 'rate_limited') or (reason == 'paywall' and code != 200):
                            raise RuntimeError(reason)
                        if mode == 'auto' and (reason == 'empty' or config.get('scroll') or config.get('wait_for')):
                            mode = 'browser'
                if mode == 'browser':
                    used = 'crawl4ai-playwright'
                    # Use a fresh context per origin to keep saved sessions separate.
                    if browser is None or getattr(browser, '_saved_origin', '') != (str(state), with_state):
                        browser = await stack.enter_async_context(AsyncWebCrawler(config=BrowserConfig(
                            headless=True, storage_state=str(state) if with_state else None)))
                        browser._saved_origin = (str(state), with_state)
                    last_error = None
                    for retry in range(2):
                        try:
                            result = await browser.arun(url=url, config=CrawlerRunConfig(
                                cache_mode=CacheMode.BYPASS, page_timeout=45000,
                                scan_full_page=config.get('scroll', False),
                                wait_for=('css:' + config['wait_for']) if config.get('wait_for') else None,
                                delay_before_return_html=1.0))
                            html, code = result.html or '', result.status_code or 200
                            reason = classify(html, code)
                            if reason != 'ok' and not (reason == 'paywall' and code == 200):
                                raise RuntimeError(reason)
                            structural_only = code == 200 and ('Structural:' in str(result.error_message) or reason == 'paywall')
                            if not result.success and not structural_only:
                                raise RuntimeError(result.error_message)
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                            if str(exc) in ('blocked', 'verification', 'login', 'rate_limited', 'paywall'):
                                break
                            if retry == 0:
                                await asyncio.sleep(2)
                    if last_error:
                        raise last_error
                reason = classify(html, code)
                if reason != 'ok' and not (reason == 'paywall' and code == 200):
                    raise RuntimeError(reason)
                page = page_record(url, html, used)
                page['access_mode'] = 'saved-state' if with_state else 'anonymous'
                from image_assets import collect_images
                await asyncio.to_thread(collect_images, page, folder)
                new_rows = extract(page.get('content_html') or html, url, config.get('fields', []), config.get('row', '')) if config.get('fields') else [
                    {'来源网址': url, '标题': page['title'], '正文': page['text']}]
                pages.append(page)
                clear_restriction(url)
                if page.get('partial_content'):
                    for item in new_rows:
                        item['内容范围'] = '部分内容／试读，非全文'
                rows.extend(new_rows)
                successful.add(url)
                for target in discover(html, url, config):
                    if target not in seen and target not in queue and len(queue) < 1000:
                        queue.append(target)
            except Exception as exc:
                message = str(exc)
                if message in ('blocked', 'verification', 'rate_limited'):
                    record_denial(url, message)
                failures.append({'url': url, 'reason': message,
                    'needs_user': message in ('blocked', 'verification', 'rate_limited', 'login', 'session_required', 'cooldown', 'paywall') or '403' in message,
                    'engine': used, 'access_mode': 'saved-state' if with_state else 'anonymous',
                    'cooldown_seconds': remaining(url), 'denial_count': denial_count(url)})
            checkpoint(current=url)
            if queue:
                await asyncio.sleep(1)
    result = checkpoint('finished')
    if not pages and failures:
        result['error'] = failures[0]['reason']
    return result


if __name__ == '__main__':
    source, output = map(Path, sys.argv[1:])
    try:
        config = read(source)
        validate_url(config['url'])
        result = asyncio.run(run(config, source.parent))
    except Exception as exc:
        result = read(output, {'pages': [], 'rows': [], 'failures': []})
        result['error'] = str(exc)
    save(output, result)
    sys.exit(1 if result.get('error') else 0)
