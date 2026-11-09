import tempfile
import io
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import app
from content import classify, page_record
from storage import read


ARTICLE = '<title>微信公众平台</title><h1 id="activity-name">测试公众号文章</h1><div id="js_content"><p>' + '这是验证后已经显示的文章正文。' * 12 + '</p><img src="https://example.com/photo.png"></div><aside>推荐列表不应保存</aside>'
CHALLENGE = '<title>微信公众平台</title><h2>环境异常</h2><p>当前环境异常，完成验证后即可继续访问。</p><a>去验证</a>'


class WechatCapture(unittest.TestCase):
    def test_challenge_detection(self):
        for markup in (CHALLENGE, '<title>环境异常</title><p>去验证</p>',
                       '<form action="/mp/wappoc_appmsgcaptcha">去验证</form>'):
            self.assertEqual(classify(markup), 'verification')
            with self.assertRaises(ValueError):
                page_record('https://mp.weixin.qq.com/s/test', markup, 'test')

    def test_article_scope_and_no_false_positive(self):
        page = page_record('https://mp.weixin.qq.com/s/test', ARTICLE, 'test')
        self.assertEqual(page['extraction'], 'wechat-article')
        self.assertEqual(page['title'], '测试公众号文章')
        self.assertNotIn('推荐列表', page['text'])
        self.assertEqual(len(page['images']), 1)
        self.assertEqual(classify(ARTICLE.replace('文章正文', '环境异常的原因')), 'ok')
        self.assertEqual(classify(ARTICLE.replace('文章正文', '当前环境异常，完成验证后即可继续访问')), 'ok')
        with self.assertRaises(ValueError):
            page_record('https://mp.weixin.qq.com/s/test', '<main>' + '推荐文章' * 60 + '</main>', 'test')

    def test_snapshot_endpoint(self):
        client = TestClient(app.app, raise_server_exceptions=False)
        with tempfile.TemporaryDirectory() as tmp, patch('app.job_folder', side_effect=lambda key: Path(tmp) / key):
            headers = {'X-Token': app.TOKEN}
            payload = {'url': 'https://mp.weixin.qq.com/s/test', 'html': CHALLENGE}
            self.assertEqual(client.post('/api/browser/page', json=payload).status_code, 403)
            self.assertEqual(client.post('/api/browser/page', json=payload, headers=headers).status_code, 400)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            payload['html'] = ARTICLE
            response = client.post('/api/browser/page', json=payload, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            folder = Path(tmp) / response.json()['id']
            record = read(folder / 'result.json')['pages'][0]
            self.assertEqual(record['engine'], 'extension-current-tab')
            self.assertEqual(read(folder / 'status.json')['status'], 'done')
            self.assertIn('测试公众号文章', client.get('/api/export/' + folder.name + '?format=md').text)
            self.assertEqual(client.post('/api/browser/page', json={**payload, 'html': 'x' * 2_000_001}, headers=headers).status_code, 413)

    def test_distributed_extensions_include_capture_script(self):
        client = TestClient(app.app)
        for endpoint, prefix in (('extension', 'browser-extension'), ('cookie-editor', 'CookieEditor-Collector')):
            response = client.get('/api/browser/' + endpoint + '.zip')
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                self.assertIn(prefix + '/current-tab.js', archive.namelist())
                self.assertIn(prefix + '/author-batch.js', archive.namelist())
                self.assertIn(b'chrome.scripting.executeScript', archive.read(prefix + '/current-tab.js'))


if __name__ == '__main__':
    unittest.main()
