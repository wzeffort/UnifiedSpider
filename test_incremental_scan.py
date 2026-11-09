import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

import article_store
import author_batch as batch
from test_author_batch import LIST, POST


class IncrementalScan(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        mock = patch('author_batch.job_folder', side_effect=lambda key: self.root / key)
        mock.start()
        self.addCleanup(mock.stop)
        self.clock = patch('author_batch.time.time', return_value=2_000_000_000).start()
        self.addCleanup(patch.stopall)
        old = batch.create({'url': 'https://xueqiu.com/u/123'})
        for n in range(1, 171):
            article_store.put(self.root / old['id'], {'url': self.url(n), 'title': str(n), 'text': '旧文章', 'markdown': '旧文章', 'images': []})

    def url(self, n):
        return f'https://xueqiu.com/123/{n}'

    def start(self, mode='incremental'):
        return batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'scan_mode': mode})['id'], 'resume')

    def report(self, state, numbers, **scan):
        self.clock.return_value += 4
        return batch.report(state['id'], {'revision': state['revision'], 'url': state['url'],
                                         'html': LIST, 'links': [self.url(n) for n in numbers], 'scan': scan})

    def test_latest_article_collected_then_stop_at_old_boundary(self):
        state = self.start()
        state = self.report(state, [1, 171])  # Pinned old post followed by latest post.
        self.assertEqual(state['discovered'], 1)
        for n in (10, 20, 30):
            state = self.report(state, [1, 171] + list(range(10, n + 10)))
        self.assertEqual(state['phase'], 'capture')
        self.assertFalse(state['history_complete'])
        self.assertEqual(batch.load(state['id'])['urls'], [self.url(171)])
        self.clock.return_value += 4
        state = batch.report(state['id'], {'revision': state['revision'], 'url': state['url'], 'html': POST})
        self.assertEqual(state['saved'], 1)
        self.assertEqual(state['state'], 'finished')

    def test_polling_same_screen_or_loading_cannot_stop_scan(self):
        state = self.start()
        for _ in range(6):
            state = self.report(state, range(1, 31))
        self.assertEqual(state['phase'], 'scan')
        for n in (40, 50, 60):
            state = self.report(state, range(n, n+10), loading=True)
        self.assertEqual(state['phase'], 'scan')
        self.assertEqual(batch.load(state['id'])['old_batches'], 1)

    def test_new_or_previously_failed_article_resets_boundary(self):
        state = self.start()
        state = self.report(state, range(1, 11))
        state = self.report(state, range(11, 21))
        state = self.report(state, [172])
        self.assertEqual(batch.load(state['id'])['old_batches'], 0)
        state = self.report(state, range(21, 41))
        self.assertEqual(state['phase'], 'scan')
        self.assertEqual(state['discovered'], 1)

    def test_history_mode_continues_past_old_articles(self):
        state = self.start('history')
        for n in (1, 11, 21, 31):
            state = self.report(state, range(n, n+10))
        self.assertEqual(state['phase'], 'scan')
        for _ in range(2):
            state = self.report(state, [171], explicit_end=True)
        self.assertEqual(state['phase'], 'capture')
        self.assertTrue(state['history_complete'])
        self.assertEqual(state['discovered'], 1)

    def test_no_new_articles_finishes_without_postprocessing(self):
        state = self.start()
        with patch('author_pipeline.enqueue') as enqueue:
            for n in (1, 11, 21):
                state = self.report(state, range(n, n+10))
            self.assertEqual(state['state'], 'finished')
            self.assertEqual(state['saved'], 0)
            enqueue.assert_not_called()

    def test_default_and_validation(self):
        state = batch.create({'url': 'https://xueqiu.com/u/123'})
        self.assertEqual(state['scan_mode'], 'incremental')
        with self.assertRaises(ValueError):
            batch.create({'url': 'https://xueqiu.com/u/123', 'scan_mode': 'invalid'})

    def test_incremental_new_article_auto_ocr_and_author_export(self):
        import author_pipeline
        import hashlib
        config = {'mode': 'folder', 'folder': str(self.root / 'export')}
        def download(url, target, budget):
            path = target / 'new.png'
            path.write_bytes(b'new image')
            return path
        with patch('download_settings.settings', return_value=config), patch('mineru_client.token', return_value='fixture'), patch('rag_assets.download', side_effect=download) as fetch, patch('mineru_client.recognize', return_value={'engine': 'mineru', 'text': '新图片', 'image_sha256': hashlib.sha256(b'new image').hexdigest()}) as ocr:
            state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'auto_after': True})['id'], 'resume')
            state = self.report(state, [171])
            for n in (1, 11, 21):
                state = self.report(state, range(n, n+10))
            self.clock.return_value += 4
            state = batch.report(state['id'], {'revision': state['revision'], 'url': state['url'], 'html': POST.replace('</div>', '<img src="https://example.com/new.png"></div>')})
            deadline = time.monotonic() + 10
            while state['id'] in author_pipeline.PENDING and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertNotIn(state['id'], author_pipeline.PENDING)
            data = batch.load(state['id'])
            self.assertEqual(data['auto_state'], 'done')
            self.assertEqual(data['last_export']['documents_count'], 1)
            self.assertEqual(data['last_export']['author_documents_count'], 171)
            self.assertEqual(Path(data['last_export']['folder']), self.root / 'export' / 'xueqiu_123')
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(ocr.call_count, 1)


if __name__ == '__main__':
    unittest.main()
