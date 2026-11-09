import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import article_store
import author_batch as batch
import rag_assets
from author_archive import author_key
from storage import save


class AuthorArchive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for target, value in [('author_batch.job_folder', lambda key: self.root / key),
                              ('download_settings.settings', lambda: {'mode': 'folder', 'folder': str(self.root / 'out')})]:
            p = patch(target, side_effect=value)
            p.start()
            self.addCleanup(p.stop)

    def task(self, url='https://xueqiu.com/u/123'):
        return batch.create({'url': url})['id']

    def page(self, key, number, images=None, host='xueqiu.com'):
        page = {'url': f'https://{host}/123/{number}', 'title': '文章' + str(number),
                'text': '正文' + str(number), 'markdown': '正文', 'images': images or []}
        article_store.put(self.root / key, page, replace=True)
        return page

    def docs(self, exported):
        return [json.loads(s) for s in Path(exported['documents_file']).read_text(encoding='utf-8').splitlines()]

    def test_history_incremental_canonical_dedup_and_no_rewrite(self):
        old = self.task()
        self.page(old, 1)
        first = batch.save_to_folder(old)
        md = next(Path(first['folder']).glob('*.md'))
        before = md.stat().st_mtime_ns
        newer = self.task('https://www.xueqiu.com/u/123')
        self.page(newer, 2, host='www.xueqiu.com')
        self.page(newer, 1, host='www.xueqiu.com')
        merged = batch.save_to_folder(newer)
        self.assertEqual(first['folder'], merged['folder'])
        self.assertEqual(merged['author_documents_count'], 2)
        self.assertEqual(len(self.docs(merged)), 2)
        self.assertEqual(md.stat().st_mtime_ns, before)
        self.assertTrue(batch.save_to_folder(newer)['reused'])
        self.assertEqual(len(list(Path(merged['folder']).glob('*.md'))), 2)
        # An earlier task cannot remove later documents.
        self.assertEqual(batch.save_to_folder(old)['author_documents_count'], 2)
        known = batch.previously_saved(batch.source_info('https://xueqiu.com/u/123'), 'new')
        self.assertEqual(len(known), 2)

    def test_old_ocr_preserved_images_reused_and_only_new_image_processed(self):
        old = self.task()
        image_dir = self.root / old / 'images'
        image_dir.mkdir()
        path = image_dir / 'fixture.png'
        path.write_bytes(b'fixture')
        image = {'url': 'https://example.com/image.png', 'file': 'images/fixture.png',
                 'ocr': {'engine': 'mineru', 'text': '识别结果', 'image_sha256': hashlib.sha256(b'fixture').hexdigest()}}
        self.page(old, 1, [image])
        batch.save_to_folder(old)
        newer = self.task()
        self.page(newer, 2, [{'url': image['url']}])
        with patch('rag_assets.download') as download, patch('mineru_client.recognize') as recognize:
            rag_assets.run(newer, self.root / newer, 'mineru')
            download.assert_not_called()
            recognize.assert_not_called()
        result = article_store.result(self.root / newer)['pages'][0]
        self.assertEqual(result['images'][0]['ocr']['text'], '识别结果')
        merged = batch.save_to_folder(newer)
        self.assertEqual(len(list((Path(merged['folder']) / 'images').iterdir())), 1)
        # Duplicate body without OCR must not erase earlier recognition.
        self.page(newer, 1, [{'url': image['url']}])
        docs = self.docs(batch.save_to_folder(newer))
        self.assertTrue(all(d['images'][0].get('ocr') for d in docs))

    def test_user_edits_backed_up_and_active_jobs_untouched(self):
        old = self.task()
        self.page(old, 1)
        result = batch.save_to_folder(old)
        md = next(Path(result['folder']).glob('*.md'))
        md.write_text('my annotation', encoding='utf-8')
        batch.save_to_folder(old)
        backups = list((md.parent / '_user_backups').iterdir())
        self.assertEqual(backups[0].read_text(encoding='utf-8'), 'my annotation')
        active = self.task()
        self.page(active, 2)
        data = batch.load(active)
        data['state'] = 'running'
        save(self.root / active / 'author-batch.json', data)
        before = (self.root / active / 'author-batch.json').read_bytes()
        self.assertEqual(batch.save_to_folder(old)['author_documents_count'], 1)
        self.assertEqual((self.root / active / 'author-batch.json').read_bytes(), before)

    def test_wechat_identity_does_not_merge_unknown_accounts(self):
        self.assertNotEqual(author_key(batch.source_info('https://mp.weixin.qq.com/s/one')),
                            author_key(batch.source_info('https://mp.weixin.qq.com/s/two')))

    def test_interrupted_export_stays_unready_until_retry(self):
        import author_archive
        from storage import read
        key = self.task()
        self.page(key, 1)
        initial = batch.save_to_folder(key)
        self.page(key, 2)
        original = author_archive.write_changed
        calls = []
        def interrupted(*args):
            calls.append(args)
            if len(calls) == 2:
                raise OSError('simulated disk error')
            return original(*args)
        with patch('author_archive.write_changed', side_effect=interrupted):
            with self.assertRaises(OSError):
                batch.save_to_folder(key)
        self.assertFalse(read(Path(initial['folder']) / 'export.json')['ready'])
        recovered = batch.save_to_folder(key)
        self.assertTrue(recovered['ready'])
        self.assertEqual(len(self.docs(recovered)), 2)


if __name__ == '__main__':
    unittest.main()
