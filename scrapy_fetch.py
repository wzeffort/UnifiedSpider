"""A separate Scrapy reactor process: HTTP retries, compression and timeouts."""
import json
import sys
import scrapy
from scrapy.crawler import CrawlerProcess
from storage import save


class FetchSpider(scrapy.Spider):
    name = 'unified_http'

    async def start(self):
        yield scrapy.Request(self.config['url'], callback=self.parse, errback=self.failed,
                             meta={'handle_httpstatus_all': True})

    def parse(self, response):
        content_type = response.headers.get('Content-Type', b'').decode('latin1').lower()
        if not hasattr(response, 'text'):
            self.output.update(error='暂不支持下载此二进制文件，请使用原网站下载', status=response.status)
        else:
            self.output.update(url=response.url, status=response.status, html=response.text,
                               content_type=content_type)

    def failed(self, failure):
        self.output.update(error=str(failure.value))


if __name__ == '__main__':
    config = json.loads(sys.argv[1])
    result = {}
    process = CrawlerProcess(settings={
        'LOG_LEVEL': 'WARNING', 'RETRY_TIMES': 2,
        'RETRY_HTTP_CODES': [408, 429, 500, 502, 503, 504],
        'DOWNLOAD_TIMEOUT': 25, 'DOWNLOAD_MAXSIZE': 12 * 1024 * 1024,
        'AUTOTHROTTLE_ENABLED': True, 'AUTOTHROTTLE_START_DELAY': 1,
        'AUTOTHROTTLE_MAX_DELAY': 10, 'CONCURRENT_REQUESTS': 1,
        'TELNETCONSOLE_ENABLED': False,
        'USER_AGENT': 'UnifiedSpider/2.0 (local research collector)',
    })
    process.crawl(FetchSpider, config=config, output=result)
    process.start()
    save(sys.argv[2], result or {'error': 'Scrapy 未返回响应'})
