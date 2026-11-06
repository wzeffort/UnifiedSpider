import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import mineru_client as m


def result_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('full.md', '<table><tr><td>代码</td><td>名称</td></tr><tr><td>000333</td><td>美的集团</td></tr></table>')
    return buffer.getvalue()


class MineruTests(unittest.TestCase):
    def test_tables_remain_structured(self):
        result = m.decode_result(result_zip())
        self.assertEqual(result['tables'][0][1], ['000333', '美的集团'])
        self.assertFalse(result['verified'])
        self.assertIn('<table>', result['markdown'])

    def test_resume_timeout_and_cache_without_duplicate_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'image.png'
            path.write_bytes(b'fixture')
            calls = []
            def api(method, route, payload=None):
                calls.append(method)
                if method == 'POST':
                    return {'batch_id': 'test-id', 'file_urls': ['https://example.com/upload']}
                return {'extract_result': [{'state': 'done', 'full_zip_url': 'https://example.com/result'}]}
            with patch.object(m, 'CACHE', Path(tmp) / 'cache'), patch.object(m, 'api', side_effect=api), patch.object(m, 'remote', return_value=result_zip()) as remote:
                with self.assertRaisesRegex(ValueError, '不重复上传'):
                    m.recognize(path, timeout=0)
                self.assertEqual(calls, ['POST'])
                result = m.recognize(path)
                self.assertEqual(calls, ['POST', 'GET'])
                self.assertEqual(m.recognize(path), result)
                self.assertEqual(calls, ['POST', 'GET'])
                self.assertEqual(remote.call_count, 2)

    def test_secret_is_not_in_network_error(self):
        import requests
        with patch.object(m, 'token', return_value='private-test-token'), patch.object(m.requests, 'request', side_effect=requests.Timeout('private-test-token')):
            with self.assertRaises(ValueError) as error:
                m.api('GET', '/example')
            self.assertNotIn('private-test-token', str(error.exception))

    def test_windows_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'MINERU_API_TOKEN': ''}):
            with patch.object(m, 'SECRET', Path(tmp) / 'token.dpapi'):
                m.set_token('test-credential')
                self.assertNotIn(b'test-credential', m.SECRET.read_bytes())
                self.assertEqual(m.token(), 'test-credential')


if __name__ == '__main__':
    unittest.main()
