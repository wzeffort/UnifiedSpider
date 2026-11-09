import unittest
from core import extract, preview_html, csv_bytes, validate_url


class CoreTests(unittest.TestCase):
    def test_block_detection_and_structural_false_positive(self):
        from content import classify
        self.assertEqual(classify('<main>' + '正文内容 ' * 200 + '</main>', 403), 'blocked')
        self.assertEqual(classify('<title>安全验证</title><p>请完成验证</p>'), 'verification')
        self.assertEqual(classify('<input type="password"><p>Sign in to continue</p>'), 'login')
        self.assertEqual(classify('<main>' + '正文内容 ' * 200 + '</main>'), 'ok')

    def test_repeated_rows_and_relative_links(self):
        html = '<div class="item"><a href="/a">甲</a></div><div class="item"><a href="/b">乙</a></div>'
        rows = extract(html, 'https://example.com/list', [{'name': '标题', 'selector': 'a'}, {'name': '链接', 'selector': 'a', 'attr': 'href'}], '.item')
        self.assertEqual([r['标题'] for r in rows], ['甲', '乙'])
        self.assertEqual(rows[1]['链接'], 'https://example.com/b')

    def test_preview_removes_active_content(self):
        safe = preview_html('<script>alert(1)</script><img src="https://evil.test" onerror="alert(1)"><p>ok</p>')
        self.assertNotIn('script', safe)
        self.assertNotIn('onerror', safe)
        self.assertNotIn('https://', safe)
        self.assertIn('ok', safe)

    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            validate_url('file:///C:/secret')

    def test_csv_formula(self):
        self.assertIn("'=1+1", csv_bytes([{'value': '=1+1'}]).decode('utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
