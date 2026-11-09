import json
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import article_store
import author_batch as batch
import author_pipeline


class Pipeline(unittest.TestCase):
    def test_capture_continues_while_ocr_is_blocked(self):
        from tests.unit.test_author_batch import LIST, POST
        import rag_assets
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def recognize(path):
                entered.set()
                if not release.wait(8):
                    raise ValueError('test gate timed out')
                return {'engine': 'mineru', 'text': '图片内容', 'image_sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest()}
            def download(url, target, budget):
                path = target / 'fixture.png'
                path.write_bytes(b'fixture')
                return path
            with patch('author_batch.job_folder', side_effect=lambda id: root / id), patch('download_settings.settings', return_value={'mode': 'folder', 'folder': str(root / 'output')}), patch('mineru_client.token', return_value='fixture'), patch('mineru_client.recognize', side_effect=recognize), patch('rag_assets.download', side_effect=download), patch('author_batch.time.time', return_value=2_000_000_000) as clock:
                task = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 2, 'auto_after': True})['id'], 'resume')
                def report(state, html, **extra):
                    clock.return_value += 4
                    return batch.report(state['id'], {'revision': state['revision'], 'url': state['url'], 'html': html, **extra})
                task = report(task, LIST, links=['https://xueqiu.com/123/1', 'https://xueqiu.com/123/2'])
                task = report(task, POST.replace('</div>', '<img src="https://example.com/image.png"></div>'))
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(batch.load(task['id'])['revision'], task['revision'])
                    paused = batch.control(task['id'], 'pause')
                    task = batch.control(paused['id'], 'resume')
                    task = report(task, POST)
                    self.assertEqual(task['saved'], 2)
                    self.assertEqual(task['state'], 'finished')
                    self.assertFalse(release.is_set())
                    # A finished author's blocked OCR must not block a new author's capture.
                    other = batch.control(batch.create({'url': 'https://xueqiu.com/u/456', 'limit': 1})['id'], 'resume')
                    other = report(other, LIST, links=['https://xueqiu.com/456/1'])
                    other = report(other, POST)
                    self.assertEqual(other['saved'], 1)
                    self.assertEqual(other['state'], 'finished')
                    self.assertFalse(release.is_set())
                finally:
                    release.set()
                    self.wait(task['id'])
                self.assertEqual(batch.load(task['id'])['auto_state'], 'done')

    def test_automatic_partial_export_retry_and_pinned_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chosen = {'mode': 'folder', 'folder': str(root / 'chosen')}
            with patch('author_batch.job_folder', side_effect=lambda id: root / id), patch('download_settings.settings', return_value=chosen) as config, patch('mineru_client.token', return_value='fixture'), patch('mineru_client.recognize', side_effect=[ValueError('temporary timeout'), {'engine': 'mineru', 'text': '图片文字', 'tables': [], 'verified': False}]) as recognize:
                task = batch.create({'url': 'https://mp.weixin.qq.com/s/test', 'auto_after': True})
                folder = root / task['id']
                (folder / 'images').mkdir()
                (folder / 'images' / 'image.png').write_bytes(b'fixture')
                article_store.put(folder, {'url': 'https://mp.weixin.qq.com/s/test', 'title': '测试', 'text': '正文', 'markdown': '正文', 'images': [{'url': 'https://example.com/img', 'file': 'images/image.png'}]})
                data = batch.load(task['id'])
                data.update(cursor=1, state='finished')
                config.return_value = {'mode': 'folder', 'folder': str(root / 'changed')}
                batch.persist(data)
                self.wait(task['id'])
                data = batch.load(task['id'])
                self.assertEqual(data['auto_state'], 'partial')
                self.assertTrue(Path(data['last_export']['folder']).is_relative_to(root / 'chosen'))
                self.assertTrue(Path(data['last_export']['documents_file']).is_file())
                # Retry explicitly adopts the currently selected destination.
                batch.control(task['id'], 'retry-output')
                self.wait(task['id'])
                data = batch.load(task['id'])
                self.assertEqual(data['auto_state'], 'done')
                self.assertTrue(Path(data['last_export']['folder']).is_relative_to(root / 'changed'))
                doc = json.loads(Path(data['last_export']['documents_file']).read_text(encoding='utf-8'))
                self.assertEqual(doc['images'][0]['ocr']['text'], '图片文字')
                self.assertNotIn('error', doc['images'][0])
                self.assertEqual(recognize.call_count, 2)

    def wait(self, id):
        deadline = time.monotonic() + 10
        while id in author_pipeline.PENDING and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertNotIn(id, author_pipeline.PENDING)


if __name__ == '__main__':
    unittest.main()
