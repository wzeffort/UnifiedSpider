import unittest
from unittest.mock import patch
from default_browser import browser_info, open_default
from browser_state_capture import page_ready


class BrowserTests(unittest.TestCase):
    def test_edge_association(self):
        with patch('default_browser.sys.platform', 'win32'), patch('default_browser.association', return_value='MSEdgeHTM'):
            self.assertEqual(browser_info()['name'], 'Microsoft Edge')

    def test_unknown_association_is_not_guessed(self):
        with patch('default_browser.sys.platform', 'win32'), patch('default_browser.association', side_effect=OSError):
            self.assertFalse(browser_info()['detected'])

    def test_chrome_and_unsupported_browser(self):
        with patch('default_browser.sys.platform', 'win32'), patch('default_browser.association', return_value='ChromeHTML') as lookup:
            info = browser_info('http')
            lookup.assert_called_once_with('http')
            self.assertEqual(info['name'], 'Google Chrome')
            self.assertEqual(info['extension_manager'], 'chrome://extensions')
            self.assertTrue(info['extension_supported'])
        with patch('default_browser.sys.platform', 'win32'), patch('default_browser.association', return_value='FirefoxURL-123'):
            self.assertFalse(browser_info()['extension_supported'])

    def test_shell_dispatch_without_profile_or_command(self):
        with patch('default_browser.sys.platform', 'win32'), patch('default_browser.os.startfile', create=True) as start:
            result = open_default('https://example.com/a?b=1&c=2')
            start.assert_called_once_with('https://example.com/a?b=1&c=2')
            self.assertTrue(result['ok'])
            for url in ('file:///C:/Windows', 'javascript:alert(1)', 'https://user:password@example.com', 'https://example.com/\n'):
                with self.assertRaises(ValueError):
                    open_default(url)
            self.assertEqual(start.call_count, 1)

    def test_error_page_must_not_trigger_auto_capture(self):
        target = 'https://example.com/a'
        for current, status in ((target, 0), (target, 403), (target, None), ('chrome-error://chromewebdata/', 200), ('https://other.com/', 200)):
            self.assertFalse(page_ready(target, current, status))
        self.assertTrue(page_ready(target, 'https://example.com/login', 200))
