import json
import unittest
from unittest.mock import patch
from app import export


class JsonExport(unittest.TestCase):
    def test_pretty_json_preserves_data(self):
        data = {'rows': [{'标题': '中文标题', '正文': '第一段\n第二段'}], 'failures': [],
                'pages': [{'title': '中文标题', 'url': 'https://example.com', 'html': '<p>原始网页</p>', 'text': '第一段\n第二段'}]}
        with patch('app.get_result', return_value=data):
            response = export('00000000-0000-0000-0000-000000000000', 'json')
        text = response.body.decode('utf-8')
        self.assertIn('\n  "rows": [\n    {', text)
        self.assertIn('中文标题', text)
        self.assertGreater(len(text.splitlines()), 10)
        self.assertEqual(json.loads(text)['rows'], data['rows'])
        self.assertNotIn('html', json.loads(text)['pages'][0])
        self.assertTrue(text.endswith('\n'))


if __name__ == '__main__':
    unittest.main()
