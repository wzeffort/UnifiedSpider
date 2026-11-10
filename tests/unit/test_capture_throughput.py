import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import article_store
import author_batch as batch
from storage import save
from tests.unit.test_author_batch import LIST, POST


class Throughput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        mock = patch('author_batch.job_folder', side_effect=lambda id: self.root/id)
        mock.start();self.addCleanup(mock.stop)
        self.now = 2_000_000_000
        clock = patch('author_batch.time.time', side_effect=lambda: self.now)
        clock.start();self.addCleanup(clock.stop)

    def task(self):
        t = batch.control(batch.create({'url':'https://xueqiu.com/u/123','limit':2})['id'],'resume')
        return batch.report(t['id'], dict(revision=t['revision'],url=t['url'],html=LIST,
                                         links=['https://xueqiu.com/123/1','https://xueqiu.com/123/2']))

    def test_exclusive_lease_expiry_and_duplicate_report(self):
        t = self.task();self.now += 4
        a='11111111-1111-1111-1111-111111111111'
        b='22222222-2222-2222-2222-222222222222'
        first=batch.claim(t['id'],a)
        self.assertEqual(batch.claim(t['id'],b)['status'],'busy')
        payload=dict(revision=t['revision'],url=t['url'],html=POST,capture_lease=first['lease'])
        with self.assertRaisesRegex(ValueError,'领取已失效'):
            batch.report(t['id'],{**payload,'capture_lease':'wrong'})
        self.now += 61
        second=batch.claim(t['id'],b)
        with self.assertRaisesRegex(ValueError,'领取已失效'):
            batch.report(t['id'],payload)
        payload['capture_lease']=second['lease']
        result=batch.report(t['id'],payload)
        self.assertEqual(result['saved'],1)
        self.assertEqual(batch.report(t['id'],payload)['saved'],1)
        self.assertEqual(batch.public(batch.load(t['id']))['processed'],1)
        self.assertNotIn('lease',batch.public(batch.load(t['id'])))

    def test_pause_invalidates_pending_submission(self):
        t=self.task();self.now+=4
        lease=batch.claim(t['id'],'11111111-1111-1111-1111-111111111111')
        batch.control(t['id'],'pause')
        result=batch.report(t['id'],dict(revision=t['revision'],url=t['url'],html=POST,capture_lease=lease['lease']))
        self.assertEqual(result['saved'],0)
        self.assertEqual(result['state'],'paused')

    def test_indexed_dedup_checks_other_host_and_new_rows(self):
        t=self.task()
        other=batch.create({'url':'https://www.xueqiu.com/u/123'})
        folder=self.root/other['id']
        page=dict(url='https://www.xueqiu.com/123/1',title='t',text='body')
        self.assertFalse(batch.already_saved(batch.load(t['id'])['source'],t['id'],t['url']))
        article_store.put(folder,page)
        with patch('article_store.urls', side_effect=AssertionError('must use indexed lookup')):
            self.assertTrue(batch.already_saved(batch.load(t['id'])['source'],t['id'],t['url']))
        self.now+=4
        result=batch.report(t['id'],dict(revision=t['revision'],url=t['url'],html=POST))
        self.assertEqual(result['saved'],0)
        self.assertEqual(result['skipped_existing'],1)

    def test_small_image_stats_cache_and_invalidation(self):
        folder=self.root/'stats';folder.mkdir()
        page=dict(url='https://example.com/1',title='t',text='body'*25000,
                  images=[{'file':'a','ocr':{'text':'ocr'*1000}},{'error':'failed'},{'url':'pending'}])
        article_store.put(folder,page)
        first=article_store.image_counts(folder)
        self.assertEqual((first['complete'],first['failed'],first['pending']),(1,1,1))
        with patch('article_store.connect',side_effect=AssertionError('unchanged stats should use cache')):
            self.assertEqual(article_store.image_counts(folder),first)
        page['images'][2]['ocr']={'text':'done'}
        article_store.put(folder,page,replace=True)
        self.assertEqual(article_store.image_counts(folder)['complete'],2)
        self.assertLess(len(json.dumps(first)),250)
        old=self.root/'legacy';old.mkdir();save(old/'result.json',{'pages':[page]})
        self.assertEqual(article_store.image_counts(old)['complete'],2)

    def test_public_omits_export_hash_manifest(self):
        t=self.task();data=batch.load(t['id'])
        data['last_export']={'folder':'example','documents_count':2,'files_sha256':{'large':'manifest'}}
        self.assertNotIn('files_sha256',batch.public(data)['last_export'])
        self.assertIn('files_sha256',data['last_export'])
