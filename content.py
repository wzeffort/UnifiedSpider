import re
import json
from urllib.parse import urljoin, urlsplit, urldefrag
from bs4 import BeautifulSoup
from markdownify import markdownify


def has_paywall(soup):
    # Ignore hidden templates and unrelated global navigation promotions.
    for node in soup.select('[hidden], [aria-hidden="true"], script, style, noscript, nav, footer, aside'):
        node.decompose()
    for node in soup.select('[style]'):
        if node.attrs is None:
            continue
        if re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', node.get('style', ''), re.I):
            node.decompose()
    if soup.select_one('#content_views'):
        for gate in soup.select('.hide-article-box'):
            if re.search(r'解锁全文|订阅专栏', gate.get_text(' ', strip=True)):
                return True
    main = soup.select_one('article, main, [role=main]') or soup
    # Paid metadata alone does not mean this user lacks access: subscribers
    # may already see the complete article while this metadata remains false.
    marker_text = r'会员专享|会员可读|付费阅读|解锁全文|订阅后阅读|购买后阅读|开通.*(?:阅读全文|继续阅读)|subscribe to (?:continue|read|unlock)|members.only|unlock (?:this article|full article)'
    for node in main.select('.paywall, .Paywall, [data-paywall], [data-testid="paywall"], .PaidContent, .PurchaseButton, .paywall-overlay'):
        if re.search(marker_text, node.get_text(' ', strip=True), re.I):
            return True
    for node in main.select('button, a, [role=button]'):
        text = node.get_text(' ', strip=True)
        if len(text) < 100 and re.fullmatch(r'(?:立即)?(?:付费阅读|解锁全文|订阅后阅读|购买后阅读|开通会员(?:继续阅读|阅读全文)|成为会员继续阅读|subscribe to (?:continue reading|read this article)|unlock full article)[\s!！。]*', text, re.I):
            return True
    return False


def classify(html, status=200):
    soup = BeautifulSoup(html or '', 'html.parser')
    title = soup.title.get_text(' ', strip=True).lower() if soup.title else ''
    for node in soup.select('script, style, noscript'):
        node.decompose()
    text = soup.get_text(' ', strip=True)
    # Some sites return an error envelope with HTTP 200, or wrap it in <pre>.
    try:
        payload = json.loads(text)
        error = payload.get('error') if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get('code', ''))
            if code == '402':
                return 'paywall'
            if code.startswith(('401', '403')):
                return 'blocked'
            if code.startswith('429'):
                return 'rate_limited'
            if error.get('message'):
                return 'api_error'
    except (ValueError, TypeError):
        pass
    if status == 402:
        return 'paywall'
    if status in (401, 403):
        return 'blocked'
    if status == 429:
        return 'rate_limited'
    if status >= 400:
        return 'http_error'
    if re.search(r'just a moment|security verification|访问验证|安全验证|验证码|人机验证', title):
        return 'verification'
    if has_paywall(soup):
        return 'paywall'
    if len(text) < 1500 and (soup.select_one('input[type=password]') or re.search(r'请先登录|登录后查看|sign in to continue', text, re.I)):
        return 'login'
    if len(text) < 1500 and re.search(r'verify you are human|请完成验证|访问异常|请求过于频繁', text, re.I):
        return 'verification'
    if len(text) < 60:
        return 'empty'
    return 'ok'


def readable_text(main):
    """Keep inline words together and break only at structural boundaries."""
    clean = BeautifulSoup(str(main), 'html.parser')
    for br in clean.select('br'):
        br.replace_with('\n')
    for block in clean.select('p, div, section, article, h1, h2, h3, h4, h5, h6, li, pre, blockquote, tr'):
        block.insert_before('\n\n')
        block.insert_after('\n\n')
    for cell in clean.select('td, th'):
        cell.insert_after('\t')
    text = clean.get_text()
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text).strip()


def page_record(url, html, engine):
    limited = classify(html) == 'paywall'
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else url
    for node in soup.select('script, style, noscript, nav, footer, header'):
        node.decompose()
    main = None
    scope = 'generic'
    notes = []
    parsed = urlsplit(url)
    if parsed.hostname == 'blog.csdn.net':
        main = soup.select_one('#content_views')
        heading = soup.select_one('#articleContentId, .title-article')
        if heading:
            title = heading.get_text(' ', strip=True)
        if main is None:
            raise ValueError('未找到这篇 CSDN 文章的正文，未将推荐列表保存为文章。请打开操作浏览器确认。')
        scope = 'csdn-article'
        for node in main.select('.hljs-button, .code-toolbar, .hide-article-box, .recommend-box, .recommend-item-box'):
            node.decompose()
    if parsed.hostname in ('www.zhihu.com', 'zhuanlan.zhihu.com'):
        if parsed.path == '/search':
            main = soup.select_one('.SearchMain .List, .SearchMain .RichText, .Search-result, [data-testid="search-results"]')
            if main is None or len(main.get_text(' ', strip=True)) < 60:
                raise ValueError('保存的搜索页只有导航或热搜，没有搜索正文；请待搜索结果显示后重新保存页面。')
            scope = 'zhihu-search'
        answer = re.search(r'/answer/(\d+)', parsed.path)
        if answer:
            candidates = soup.select('.AnswerItem')
            for item in candidates:
                identified = item.get('data-aid') == answer[1]
                for anchor in item.select('meta[itemprop=url], a[itemprop=url]'):
                    identified |= bool(re.search(r'/answer/' + answer[1] + r'(?:[/?#]|$)', anchor.get('content', anchor.get('href', ''))))
                if identified:
                    main = item.select_one('.RichContent-inner, .RichText')
                    break
            if main is None and len(candidates) == 1:
                main = candidates[0].select_one('.RichContent-inner, .RichText')
            if main is None:
                notes.append('未定位到指定回答正文，当前为通用提取，请核对是否混入其他内容。')
            else:
                scope = 'zhihu-answer'
        elif parsed.path != '/search':
            main = soup.select_one('.Post-RichTextContainer, article .RichText, .Post-RichText')
            if main is not None:
                scope = 'zhihu-article'
        if soup.select_one('.RichContent-inner--collapsed'):
            notes.append('页面包含折叠内容，可能未获取全文；请在操作浏览器展开后保存。')
    main = main or soup.select_one('article, main, [role=main]') or soup.body or soup
    for node in main.select('[hidden], [aria-hidden="true"], .paywall, .Paywall, [data-paywall], .hide-article-box, .paywall-overlay'):
        node.decompose()
    for node in main.select('[style]'):
        if node.attrs is not None and re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', node.get('style', ''), re.I):
            node.decompose()
    for link in main.select('a[href]'):
        link['href'] = urljoin(url, link['href'])
    images = []
    for img in main.select('img'):
        source = next((img.get(k) for k in ('data-original', 'data-actualsrc', 'data-src', 'data-lazy-src', 'src') if img.get(k) and not img.get(k).startswith('data:')), '')
        source = urljoin(url, source)
        if urlsplit(source).scheme not in ('http', 'https'):
            continue
        img['src'] = source
        if not any(item['url'] == source for item in images):
            images.append({'url': source, 'alt': img.get('alt', '')})
    text = readable_text(main)
    if limited:
        if len(text.strip()) < 30:
            raise ValueError('该页面仅有付费提示，未找到足够的可见正文，暂无可下载内容。')
        notes.append('部分内容／试读：页面有会员或付费提示，仅保存当前可见内容，不代表全文。')
    return {'url': url, 'title': title, 'html': html, 'markdown': markdownify(str(main), heading_style='ATX', wrap=False, strip=['a']),
            'text': text, 'engine': engine, 'extraction': scope, 'notes': notes,
            'images': images, 'content_html': str(main), 'partial_content': limited}


def discover(html, url, config):
    soup = BeautifulSoup(html, 'html.parser')
    selector = config.get('next')
    links = soup.select(selector) if selector else (soup.select('a[href]') if config.get('site') else [])
    for node in links:
        href = node.get('href', '').strip()
        if not href:
            continue
        target = urldefrag(urljoin(url, href))[0]
        if urlsplit(target).scheme not in ('http', 'https') or urlsplit(target).netloc != urlsplit(config['url']).netloc:
            continue
        if re.search(r'\.(zip|exe|png|jpe?g|gif|mp4|mp3|pdf|xlsx?|docx?)(?:\?|$)', target, re.I):
            continue
        yield target
