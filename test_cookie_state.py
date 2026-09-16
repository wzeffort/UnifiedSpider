import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cookie_state import scoped_state, store_state


class Cookies(unittest.TestCase):
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
