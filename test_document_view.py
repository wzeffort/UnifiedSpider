import unittest
from content import page_record
from document_view import document_data


class Documents(unittest.TestCase):
    def test_old_export_rebuilt_without_network(self):
        page = page_record('https://example.com/article', '<article><h2>正文标题</h2><p>正文开头 <a href="https://zhida.zhihu.com/search?q=long-query">重要词语</a> 正文结尾。</p><img src="/photo.png"></article>', 'scrapy')
        page['markdown'] = 'wrong cached output'
        data = {'pages': [page], 'rows': []}
        refreshed = document_data(data)['pages'][0]
        self.assertIn('正文开头 重要词语 正文结尾。', refreshed['markdown'])
        self.assertIn('## 正文标题', refreshed['markdown'])
        self.assertIn('![](https://example.com/photo.png)', refreshed['markdown'])
        self.assertNotIn('long-query', refreshed['markdown'])
        self.assertEqual(data['pages'][0]['markdown'], 'wrong cached output')

    def test_search_shell_is_not_an_article(self):
        with self.assertRaises(ValueError):
            page_record('https://www.zhihu.com/search?q=test', '<main><a>综合</a><a>用户</a><aside>大家都在搜</aside></main>', 'scrapy')


if __name__ == '__main__':
    unittest.main()
