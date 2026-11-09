import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import article_store
import author_batch
import rag_assets
from article_metadata import extract_metadata
from storage import save


class RagPipeline(unittest.TestCase):
    def test_legacy_migration_custom_rows_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            page = {'url': 'https://example.com/1', 'title': '一', 'text': '正文'}
            old = {'pages': [page], 'rows': [{'自定义': '字段'}], 'failures': [{'reason': '旧错误'}]}
            save(folder / 'result.json', old)
            original = (folder / 'result.json').read_bytes()
            article_store.put(folder, page)
            article_store.put(folder, {**page, 'url': 'https://example.com/2'})
            article_store.put(folder, page)
            self.assertEqual(article_store.count(folder), 2)
            self.assertEqual(article_store.result(folder)['rows'], old['rows'])
            article_store.save_rows(folder, [])
            self.assertEqual(article_store.result(folder)['rows'], [])
            self.assertEqual(len(article_store.result(folder)['failures']), 1)
            self.assertEqual((folder / 'result.json').read_bytes(), original)
            article_store.put(folder, {**page, 'text': '更新'}, replace=True)
            self.assertEqual(article_store.result(folder)['pages'][0]['text'], '更新')

    def test_metadata_retains_uncertain_dates(self):
        data = extract_metadata('<meta name="author" content="作者甲"><time datetime="2026-11-05T09:00:00+08:00"></time>')
        self.assertEqual(data['author_name'], '作者甲')
        self.assertEqual(data['published_at'], '2026-11-05T09:00:00+08:00')
        self.assertEqual(extract_metadata('<span id="publish_time">2026年11月5日</span>')['published_at'], '2026-11-05')
        for text in ('昨天', '09-27 10:18', '2026-02-31'):
            data = extract_metadata('<span id="publish_time">' + text + '</span>')
            self.assertIsNone(data['published_at'])
            self.assertEqual(data['published_at_raw'], text)

    def test_legacy_generated_rows_grow_with_articles(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            page = {'url': 'https://example.com/1', 'title': '一', 'text': '正文'}
            save(folder / 'result.json', {'pages': [page], 'rows': [{'来源网址': page['url'], '标题': '一', '正文': '正文'}]})
            article_store.put(folder, {**page, 'url': 'https://example.com/2'})
            self.assertEqual(len(article_store.result(folder)['rows']), 2)

    def test_private_images_and_missing_ocr(self):
        with patch('rag_assets.socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                rag_assets.validate_image_url('https://example.com/image.png')
        with patch('rag_assets.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Tesseract'):
                rag_assets.ocr_engine()

    def test_enrichment_export_hash_and_local_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('author_batch.job_folder', side_effect=lambda id: root / id):
                batch = author_batch.create({'url': 'https://xueqiu.com/u/123'})
                folder = root / batch['id']
                page = {'url': 'https://xueqiu.com/123/1', 'title': '标题', 'text': '正文',
                        'markdown': '正文 ![图](https://example.com/a.png)',
                        'images': [{'url': 'https://example.com/a.png'}]}
                article_store.put(folder, page)
                def fake_download(url, target, budget):
                    path = target / 'test.png'
                    path.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
                    return path
                def doc():
                    with zipfile.ZipFile(io.BytesIO(author_batch.bundle(batch['id']))) as archive:
                        return json.loads(archive.read('documents.jsonl'))
                before = doc()
                with patch('rag_assets.download', side_effect=fake_download):
                    rag_assets.run(batch['id'], folder, None)
                after = doc()
                self.assertEqual(before['content_hash'], after['content_hash'])
                self.assertNotEqual(before['retrieval_hash'], after['retrieval_hash'])
                self.assertEqual(after['images'][0]['file'], 'images/test.png')
                self.assertEqual(rag_assets.status(folder)['state'], 'finished')
                with patch('download_settings.settings', return_value={'folder': str(root / 'output')}):
                    exported = author_batch.save_to_folder(batch['id'])
                    self.assertEqual(len(list((Path(exported['folder']) / 'images').glob('*.png'))), 1)
                    self.assertTrue(author_batch.save_to_folder(batch['id'])['reused'])
                rag_assets.ACTIVE.add(str(folder))
                try:
                    with self.assertRaises(ValueError):
                        author_batch.bundle(batch['id'])
                    with self.assertRaises(ValueError):
                        author_batch.control(batch['id'], 'resume')
                finally:
                    rag_assets.ACTIVE.discard(str(folder))


if __name__ == '__main__':
    unittest.main()
