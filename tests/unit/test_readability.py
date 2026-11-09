import unittest
from content import page_record, classify


class Readability(unittest.TestCase):
    def test_inline_and_scope(self):
        html = '<h1 id="articleContentId">测试文章</h1><div id="content_views"><h2>步骤</h2><p>使用 <a href="/api">DeepSeek API</a> 接入 <strong>Claude Code</strong>。</p><p>下一段。</p><pre>first\n  second</pre></div><div>推荐文章，不应导出</div>'
        page = page_record('https://blog.csdn.net/test/article/details/1', html, 'test')
        self.assertIn('使用 DeepSeek API 接入 Claude Code。', page['text'])
        self.assertNotIn('推荐文章', page['text'])
        self.assertIn('## 步骤', page['markdown'])
        self.assertIn('first\n  second', page['text'])

    def test_csdn_paywall(self):
        html = '<main><article><div id="content_views">试读文字</div></article><div class="hide-article-box">订阅专栏 解锁全文</div></main>'
        self.assertEqual(classify(html), 'paywall')

    def test_missing_article(self):
        with self.assertRaises(ValueError):
            page_record('https://blog.csdn.net/test/article/details/1', '<main>推荐列表</main>', 'test')


if __name__ == '__main__':
    unittest.main()
