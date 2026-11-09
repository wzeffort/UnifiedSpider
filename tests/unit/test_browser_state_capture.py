import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from browser_state_capture import StateCapture
from cookie_state import store_state
from site_access import record_denial, denial_count
from storage import read


class CaptureTests(unittest.TestCase):
    def test_scope_change_and_no_background_reset(self):
        with tempfile.TemporaryDirectory() as tmp, patch('cookie_state.session_path', return_value=Path(tmp) / 'state.json'), patch('site_access.DB', Path(tmp) / 'access.sqlite3'):
            url = 'https://www.example.com/article'
            context = Mock()
            context.storage_state.return_value = {'cookies': [
                {'name': 'auth', 'value': 'fixture-only', 'domain': '.example.com'},
                {'name': 'other', 'value': 'do-not-save', 'domain': '.other.com'}]}
            record_denial(url, 'blocked')
            capture = StateCapture(url)
            result = capture.capture(context)
            self.assertEqual(result['cookie_count'], 1)
            self.assertNotIn('fixture-only', str(result))
            self.assertEqual(denial_count(url), 1)
            self.assertEqual(len(read(Path(tmp) / 'state.json')['cookies']), 1)
            self.assertIsNone(capture.capture(context))
            context.storage_state.return_value['cookies'][0]['value'] = 'updated'
            self.assertIsNotNone(capture.capture(context))
            self.assertEqual(denial_count(url), 1)

    def test_empty_state_not_saved(self):
        context = Mock()
        context.storage_state.return_value = {'cookies': [], 'origins': []}
        with patch('browser_state_capture.store_state') as save:
            self.assertIsNone(StateCapture('https://example.com').capture(context))
            save.assert_not_called()

    def test_new_import_clears_pre_cooldown_count(self):
        with tempfile.TemporaryDirectory() as tmp, patch('cookie_state.session_path', return_value=Path(tmp) / 'state.json'), patch('site_access.DB', Path(tmp) / 'access.sqlite3'):
            url = 'https://example.com/'
            record_denial(url, 'blocked')
            result = store_state(url, [{'name': 'auth', 'value': 'fixture', 'domain': 'example.com'}], allow_retry=True)
            self.assertTrue(result['cooldown_reset'])
            self.assertEqual(denial_count(url), 0)
