import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import app
import author_batch as batch
import download_settings as downloads
from storage import read
from test_author_batch import POST


class LocalExports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / '我的 RAG 数据'
        for target, value in (
            ('download_settings.CONFIG', self.root / 'settings.json'),
            ('author_batch.job_folder', lambda key: self.root / key),
        ):
            mocked = patch(target, value) if isinstance(value, Path) else patch(target, side_effect=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.client = TestClient(app.app, raise_server_exceptions=False)
        self.headers = {'X-Token': app.TOKEN}

    def test_settings_and_picker_cancel(self):
        self.assertEqual(self.client.post('/api/download-settings', json={}).status_code, 403)
        for payload in ({'folder': 'relative'}, {'folder': str(self.output), 'mode': 'invalid'}):
            self.assertEqual(self.client.post('/api/download-settings', json=payload, headers=self.headers).status_code, 400)
        result = self.client.post('/api/download-settings', json={'folder': str(self.output), 'mode': 'folder'}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get('/api/download-settings').json()['folder'], str(self.output))
        with patch('download_settings.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({'folder': None})
            result = self.client.post('/api/download-settings/pick', json={}, headers=self.headers)
            self.assertTrue(result.json()['cancelled'])
            self.assertEqual(downloads.settings()['folder'], str(self.output))
            run.return_value.stdout = json.dumps({'folder': str(self.output)})
            self.assertEqual(self.client.post('/api/download-settings/pick', json={}, headers=self.headers).json()['mode'], 'folder')

    def test_save_ready_marker_idempotence_and_no_overwrite(self):
        downloads.update({'folder': str(self.output), 'mode': 'folder'})
        state = batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 1})
        # Use the queue API to save one real parsed fixture record.
        state = batch.control(state['id'], 'resume')
        state = batch.report(state['id'], {'revision': state['revision'], 'url': state['url'],
            'html': POST, 'links': ['https://xueqiu.com/123/1']})
        with patch('author_batch.time.time', return_value=4_000_000_000):
            state = batch.report(state['id'], {'revision': state['revision'], 'url': state['url'], 'html': POST})
        endpoint = '/api/authors/' + state['id'] + '/save'
        response = self.client.post(endpoint, json={}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        export = response.json()
        folder = Path(export['folder'])
        self.assertTrue(folder.is_relative_to(self.output))
        self.assertTrue(read(folder / 'export.json')['ready'])
        self.assertTrue((folder / 'documents.jsonl').is_file())
        self.assertEqual(len(list(folder.glob('*.md'))), 1)
        self.assertEqual(batch.public(batch.load(state['id']))['last_export']['folder'], str(folder))
        again = self.client.post(endpoint, json={}, headers=self.headers).json()
        self.assertEqual(again['folder'], str(folder))
        self.assertTrue(again['reused'])
        markdown = next(folder.glob('*.md'))
        markdown.unlink()
        repaired = self.client.post(endpoint, json={}, headers=self.headers).json()
        self.assertEqual(repaired['folder'], str(folder))
        self.assertEqual(len(list(Path(repaired['folder']).glob('*.md'))), 1)
        (folder / 'documents.jsonl').write_text('user-edited', encoding='utf-8')
        fresh = self.client.post(endpoint, json={}, headers=self.headers)
        self.assertEqual(fresh.status_code, 400)
        self.assertEqual((folder / 'documents.jsonl').read_text(encoding='utf-8'), 'user-edited')

    def test_validate_batch_before_creating_any_task(self):
        endpoint = '/api/authors/validate'
        response = self.client.post(endpoint, headers=self.headers, json={
            'urls': ['https://xueqiu.com/u/123', '不是网址'], 'limit': 100})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(list(self.root.glob('*/author-batch.json')))
        self.assertEqual(self.client.post(endpoint, headers=self.headers, json={
            'urls': ['https://xueqiu.com/u/123'], 'limit': 100}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
