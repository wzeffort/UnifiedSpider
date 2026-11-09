import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import site_access
from content import classify, page_record
from storage import save


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / 'state.json'
        self.db = patch.object(site_access, 'DB', Path(self.temp.name) / 'access.sqlite3')
        self.path = patch.object(site_access, 'session_path', lambda url: self.state)
        self.db.start()
        self.path.start()

    def tearDown(self):
        self.path.stop()
        self.db.stop()
        self.temp.cleanup()

    def test_missing_and_expired_state_not_login(self):
        url = 'https://www.zhihu.com/question/1/answer/2'
        self.assertTrue(site_access.needs_confirmation(url))
        save(self.state, {'cookies': [{'domain': '.zhihu.com', 'path': '/', 'expires': time.time()-1}], 'origins': []})
        self.assertFalse(site_access.applicable_state(url))
        self.assertTrue(site_access.describe(url)['state_file_exists'])
        save(self.state, {'cookies': [{'domain': '.zhihu.com', 'path': '/', 'expires': time.time()+500, 'secure': True}]})
        self.assertTrue(site_access.applicable_state(url))
        self.assertFalse(site_access.needs_confirmation(url))
        self.assertTrue(site_access.needs_confirmation(url, False))
        self.assertFalse(site_access.applicable_state('https://zhihu.com.example.test/'))
        self.assertFalse(site_access.applicable_state('http://www.zhihu.com/'))

    def test_cooldown_persists_and_is_origin_scoped(self):
        site_access.restrict('https://example.com/a', 'blocked', seconds=120)
        self.assertGreater(site_access.remaining('https://example.com/b'), 0)
        self.assertEqual(site_access.remaining('https://another.example.com'), 0)
        site_access.clear_restriction('https://example.com')
        self.assertEqual(site_access.remaining('https://example.com/b'), 0)

    def test_json_denial_even_with_http_200(self):
        error = json.dumps({'error': {'message': '您当前请求存在异常，暂时限制本次访问。', 'code': 40362}}, ensure_ascii=False)
        self.assertEqual(classify(error, 200), 'blocked')
        self.assertEqual(classify('<html><body><pre>'+error+'</pre></body></html>', 200), 'blocked')
        self.assertEqual(classify('<article><p>'+('An article about response codes. '*10)+error+'</p></article>', 200), 'ok')

    def test_three_denials_and_reset(self):
        url = 'https://example.com/a'
        for count in (1, 2):
            self.assertEqual(site_access.record_denial(url, 'blocked'), count)
            self.assertEqual(site_access.remaining(url), 0)
        self.assertEqual(site_access.denial_count('https://other.com'), 0)
        self.assertEqual(site_access.record_denial(url, 'blocked'), 3)
        self.assertGreater(site_access.remaining(url), 0)
        with site_access.connection() as db:
            before = db.execute('SELECT until FROM cooldown').fetchone()[0]
        site_access.record_denial(url, 'blocked')
        with site_access.connection() as db:
            self.assertEqual(db.execute('SELECT until FROM cooldown').fetchone()[0], before)
        site_access.clear_restriction(url)
        self.assertEqual(site_access.denial_count(url), 0)
        self.assertEqual(site_access.record_denial(url, 'blocked'), 1)

    def test_expired_count_starts_fresh(self):
        with patch('site_access.time.time', return_value=1000):
            for _ in range(3):
                site_access.record_denial('https://example.com', 'blocked')
        with patch('site_access.time.time', return_value=1301):
            self.assertEqual(site_access.remaining('https://example.com'), 0)
            self.assertEqual(site_access.record_denial('https://example.com', 'blocked'), 1)

    def test_concurrent_denials_are_not_lost(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            counts = list(pool.map(lambda _: site_access.record_denial('https://example.com', 'blocked'), range(3)))
        self.assertEqual(sorted(counts), [1, 2, 3])
        self.assertGreater(site_access.remaining('https://example.com'), 0)

    def test_target_answer_excludes_recommendations(self):
        html = '<title>Question</title><main><div class="AnswerItem" data-aid="11"><div class="RichText">Wrong answer</div></div><div class="AnswerItem" data-aid="22"><div class="RichContent-inner">Correct answer</div></div></main>'
        record = page_record('https://www.zhihu.com/question/1/answer/22', html, 'test')
        self.assertEqual(record['text'], 'Correct answer')
        self.assertEqual(record['extraction'], 'zhihu-answer')


if __name__ == '__main__':
    unittest.main()
