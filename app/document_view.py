"""Build preview and exports from a single article snapshot, without refetching."""
from copy import deepcopy
from markdownify import markdownify
from content import page_record


def document_data(data):
    result = deepcopy(data)
    for page in result['pages']:
        # Plain text imports deliberately preserve exactly what the user pasted.
        if page.get('engine') is None:
            continue
        if '/search?' in page.get('url', '') and 'zhihu.com/' in page.get('url', ''):
            rebuilt = page_record(page['url'], page['html'], page['engine'])
            page['content_html'] = rebuilt['content_html']
        if not page.get('content_html'):
            rebuilt = page_record(page['url'], page['html'], page['engine'])
            page['content_html'] = rebuilt['content_html']
        page['markdown'] = markdownify(page['content_html'], heading_style='ATX', wrap=False, strip=['a'])
    return result
