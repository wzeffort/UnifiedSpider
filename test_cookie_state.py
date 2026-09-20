import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cookie_state import scoped_state, store_state
from site_access import restrict, remaining


class Cookies(unittest.TestCase):
    def test_import_endpoint_enables_retry(self):
        from app import import_cookies
        with patch('cookie_state.store_state', return_value={'cooldown_reset': True}) as store, patch('app.SESSION_PROCESS', None):
            result = import_cookies({'url': 'https://example.com/', 'data': []})
            store.assert_called_once_with('https://example.com/', [], allow_retry=True)
            self.assertTrue(result['cooldown_reset'])

    def test_new_cookie_clears_cooldown_but_repeat_does_not(self):
        url = 'https://www.example.com/article'
        cookie = {'name': 'auth', 'value': 'fixture-a', 'domain': '.example.com', 'path': '/'}
        with tempfile.TemporaryDirectory() as tmp, patch('cookie_state.session_path', return_value=Path(tmp) / 'state.json'), patch('site_access.DB', Path(tmp) / 'access.sqlite3'):
            restrict(url, 'blocked')
            restrict('https://other.example.org', 'blocked')
            report = store_state(url, [cookie], allow_retry=True)
            self.assertTrue(report['cooldown_reset'])
            self.assertEqual(remaining(url), 0)
            self.assertGreater(remaining('https://other.example.org'), 0)
            restrict(url, 'blocked')
            repeat = store_state(url, [{**cookie, 'expires': 4102444800}], allow_retry=True)
            self.assertFalse(repeat['cooldown_reset'])
            self.assertGreater(remaining(url), 0)
            changed = store_state(url, [{**cookie, 'value': 'fixture-b'}], allow_retry=True)
            self.assertTrue(changed['cooldown_reset'])
            self.assertEqual(remaining(url), 0)

    def test_unusable_or_invalid_cookie_keeps_cooldown(self):
        url = 'https://www.example.com/article'
        with tempfile.TemporaryDirectory() as tmp, patch('cookie_state.session_path', return_value=Path(tmp) / 'state.json'), patch('site_access.DB', Path(tmp) / 'access.sqlite3'):
            restrict(url, 'blocked')
            report = store_state(url, [{'name': 'auth', 'value': 'fixture', 'domain': '.example.com', 'path': '/unrelated'}], allow_retry=True)
            self.assertFalse(report['cooldown_reset'])
            with self.assertRaises(ValueError):
                store_state(url, [{'name': 'auth', 'value': 'fixture', 'domain': '.other.com'}], allow_retry=True)
            self.assertGreater(remaining(url), 0)

    def test_scope_and_format(self):
        source = [{'name': 'auth', 'value': 'fixture-only', 'domain': '.example.com', 'expirationDate': 4102444800, 'sameSite': 'no_restriction', 'secure': True},
                  {'name': 'other', 'value': 'fixture-only', 'domain': '.other.com'},
                  {'name': 'expired', 'value': 'fixture-only', 'domain': '.example.com', 'expires': 1},
                  {'name': 'broad', 'value': 'fixture-only', 'domain': '.com'}]
        state, ignored = scoped_state('https://www.example.com/', source)
        self.assertEqual(ignored, 3)
        self.assertEqual(len(state['cookies']), 1)
        self.assertEqual(state['cookies'][0]['sameSite'], 'None')
        with tempfile.TemporaryDirectory() as tmp, patch('cookie_state.session_path', return_value=Path(tmp) / 'state.json'):
            report = store_state('https://www.example.com/', source)
            self.assertNotIn('fixture-only', str(report))
            before = (Path(tmp) / 'state.json').read_bytes()
            with self.assertRaises(ValueError):
                store_state('https://www.example.com/', [])
            self.assertEqual(before, (Path(tmp) / 'state.json').read_bytes())

    def test_storage_scope(self):
        state, _ = scoped_state('https://www.example.com/', {'cookies': [], 'origins': [
            {'origin': 'https://www.example.com', 'localStorage': [{'name': 'fixture', 'value': 'test'}]},
            {'origin': 'https://other.com', 'localStorage': [{'name': 'fixture', 'value': 'test'}]}]})
        self.assertEqual(len(state['origins']), 1)


if __name__ == '__main__':
    unittest.main()
