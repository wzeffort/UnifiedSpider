"""Opt-in capture from our visible browser only; no system-browser access."""
import json
from urllib.parse import urlsplit
from cookie_state import scoped_state, store_state


def page_ready(target, current, status):
    return (urlsplit(current).scheme in ('http', 'https')
            and urlsplit(current).netloc == urlsplit(target).netloc
            and 200 <= (status or 0) < 400)


class StateCapture:
    def __init__(self, url):
        self.url = url
        self.previous = None

    def capture(self, context):
        try:
            state, _ = scoped_state(self.url, context.storage_state(indexed_db=True))
        except ValueError:
            return None
        signature = json.dumps(state, sort_keys=True, ensure_ascii=False)
        if signature == self.previous:
            return None
        # Background cookie rotation must not silently reset the refusal budget.
        report = store_state(self.url, state)
        self.previous = signature
        return {'cookie_count': report['cookie_count'], 'message':
                f'已自动保存本站 {report["cookie_count"]} 条 Cookie，后续采集可复用。'
                '这不代表网站已确认登录，也不会自动解除等待时间。完成后可关闭浏览器并开始收集。'}
