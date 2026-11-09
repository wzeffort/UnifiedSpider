import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import author_batch as batch
from storage import read
from content import classify, page_record


LIST = '<title>作者主页</title><main>' + '这里是作者历史帖子列表。' * 20 + '</main>'
POST = '<title>测试雪球正文</title><h1>文章标题</h1><div class="article__bd">' + '这是浏览器中已经显示的历史帖子正文。' * 15 + '</div><aside>不应保存的推荐</aside>'


class AuthorBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.patch = patch('author_batch.job_folder', side_effect=lambda id: self.folder / id)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.now = 2_000_000_000
        self.clock = patch('author_batch.time.time', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def report(self, state, **payload):
        self.now += 4
        return batch.report(state['id'], {'revision': state['revision'], 'url': state['url'], 'html': LIST, **payload})

    def test_url_filtering(self):
        source = batch.source_info('https://xueqiu.com/123')
        self.assertEqual(source['owner'], '123')
        self.assertEqual(batch.article_url('https://xueqiu.com/123/456?x=1', source), 'https://xueqiu.com/123/456')
        self.assertEqual(batch.article_url('https://www.xueqiu.com/123/456', source), 'https://xueqiu.com/123/456')
        for url in ('https://xueqiu.com/999/456', 'https://evil.test/123/456', 'file:///123/456'):
            self.assertIsNone(batch.article_url(url, source))
        for url in ('行中衡', 'http://xueqiu.com/123', 'https://xueqiu.com@evil.test/123'):
            with self.assertRaises(ValueError):
                batch.source_info(url)

    def capture_task(self, count=2):
        state=batch.control(batch.create({'url':'https://xueqiu.com/u/123','limit':count})['id'],'resume')
        return self.report(state,links=['https://xueqiu.com/123/'+str(i) for i in range(count)])

    def test_redirect_retry_once_then_skip_without_saving_homepage(self):
        state=self.capture_task()
        state=self.report(state,url='https://xueqiu.com/',html=LIST)
        self.assertEqual(state['article_retry'],1)
        self.assertEqual(state['processed'],0)
        stale=state.copy()
        state=self.report(state,url='https://xueqiu.com/',html=LIST)
        self.assertEqual(state['processed'],1)
        self.assertEqual(state['saved'],0)
        self.assertEqual(state['state'],'running')
        self.assertEqual(self.report(stale,url='https://xueqiu.com/',html=LIST)['processed'],1)
        state=self.report(state,html=POST)
        self.assertEqual(state['saved'],1)
        self.assertEqual(state['state'],'finished')
        result=__import__('article_store').result(self.folder/state['id'])
        self.assertEqual(len(result['failures']),1)
        self.assertEqual(result['failures'][0]['attempts'],2)
        self.assertNotIn('https://xueqiu.com/123/0',batch.previously_saved(state['source'],'other'))

    def test_deleted_skips_but_login_and_verification_do_not(self):
        state=self.capture_task()
        state=self.report(state,html='<title>文章不存在</title><main>该文章已被删除</main>')
        self.assertEqual(state['processed'],1)
        state=self.report(state,url='https://xueqiu.com/account/login',html=LIST)
        self.assertEqual(state['state'],'needs_user')
        self.assertEqual(state['processed'],1)
        state=batch.control(state['id'],'resume')
        state=self.report(state,html='<title>安全验证</title><p>请完成验证</p>')
        self.assertEqual(state['state'],'needs_user')
        self.assertEqual(state['processed'],1)

    def test_transient_empty_retries_then_success(self):
        state=self.capture_task(1)
        state=self.report(state,html='<html><body></body></html>')
        self.assertEqual(state['article_retry'],1)
        state=self.report(state,html=POST)
        self.assertEqual(state['saved'],1)
        self.assertEqual(state['article_retry'],0)

    def test_three_consecutive_failures_pause_remaining_queue(self):
        state=self.capture_task(4)
        for _ in range(6):state=self.report(state,url='https://xueqiu.com/',html=LIST)
        self.assertEqual(state['processed'],3)
        self.assertEqual(state['state'],'needs_user')
        self.assertEqual(state['saved'],0)

    def test_short_xueqiu_post(self):
        markup = '<title>短帖</title><div class="status-content">今天的简短记录。</div>'
        self.assertEqual(classify(markup), 'ok')
        self.assertEqual(page_record('https://xueqiu.com/123/456', markup, 'test')['text'], '今天的简短记录。')

    def test_dedup_pause_resume_and_bundle(self):
        state = batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 10})
        state = batch.control(state['id'], 'resume')
        state = self.report(state, links=['https://xueqiu.com/123/1', 'https://xueqiu.com/123/1?x=1', 'https://xueqiu.com/999/2'])
        self.assertEqual(state['discovered'], 1)
        stale = state.copy()
        state = batch.control(state['id'], 'pause')
        self.assertEqual(self.report(stale, links=['https://xueqiu.com/123/2'])['discovered'], 1)
        state = batch.control(state['id'], 'finish-scan')
        state = self.report(state, html='<h1>环境异常</h1><p>当前环境异常，完成验证后即可继续访问。</p>')
        self.assertEqual(state['state'], 'needs_user')
        self.assertEqual(state['processed'], 0)
        state = batch.control(state['id'], 'resume')
        state = self.report(state, html=POST)
        self.assertEqual(state['state'], 'finished')
        self.assertEqual(state['saved'], 1)
        with zipfile.ZipFile(io.BytesIO(batch.bundle(state['id']))) as archive:
            names = archive.namelist()
            markdown = next(name for name in names if name.endswith('.md'))
            text = archive.read(markdown).decode('utf-8-sig')
            self.assertIn('文章标题', markdown)
            self.assertIn('历史帖子正文', text)
            self.assertNotIn('推荐', text)
            self.assertIn('不保证', json.loads(archive.read('采集清单.json'))['completeness'])
            documents = [json.loads(line) for line in archive.read('documents.jsonl').decode('utf-8').splitlines()]
            self.assertEqual(len(documents), 1)
            doc = documents[0]
            self.assertEqual(doc['source_url'], 'https://xueqiu.com/123/1')
            self.assertEqual(doc['author_id'], '123')
            self.assertEqual(doc['platform'], 'xueqiu')
            self.assertIsNone(doc['published_at'])
            self.assertIn('+00:00', doc['captured_at'])
            self.assertEqual(len(doc['document_id']), 64)
            self.assertEqual(len(doc['content_hash']), 64)
            self.assertIn('历史帖子正文', doc['text'])
            with zipfile.ZipFile(io.BytesIO(batch.bundle(state['id']))) as again:
                self.assertEqual(again.read('documents.jsonl'), archive.read('documents.jsonl'))

    def test_stop_discovery_and_limit(self):
        state = batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 2})
        state = batch.control(state['id'], 'resume')
        state = self.report(state, links=['https://xueqiu.com/123/' + str(i) for i in range(1, 6)])
        self.assertEqual(state['discovered'], 2)
        self.assertEqual(state['phase'], 'capture')
        state = batch.control(state['id'], 'skip')
        self.assertEqual(state['processed'], 1)
        state = self.report(state, html=POST)
        self.assertEqual(state['saved'], 1)
        self.assertEqual(len(__import__('article_store').result(self.folder / state['id'])['failures']), 1)

    def test_wechat_article_is_not_entire_history(self):
        state = batch.create({'url': 'https://mp.weixin.qq.com/s/fixture-only'})
        self.assertEqual(state['discovered'], 1)
        self.assertEqual(state['phase'], 'capture')
        self.assertIn('只保存该篇', state['message'])
        source = batch.source_info('https://mp.weixin.qq.com/mp/profile_ext?__biz=abc')
        self.assertIsNone(batch.article_url('https://mp.weixin.qq.com/s?__biz=other&mid=1&idx=1&sn=a', source))

    def test_six_empty_rounds_do_not_finish(self):
        state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123'})['id'], 'resume')
        for _ in range(6):
            state = self.report(state, links=[])
        self.assertEqual(state['state'], 'running')
        self.assertEqual(state['phase'], 'scan')
        for _ in range(24):
            state = self.report(state, links=[])
        self.assertEqual(state['state'], 'needs_user')
        self.assertEqual(state['phase'], 'scan')

    def test_scrolling_loading_and_explicit_end(self):
        state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123'})['id'], 'resume')
        for _ in range(35):
            state = self.report(state, links=['https://xueqiu.com/123/1'], scan={'progress': True})
        self.assertEqual(state['state'], 'running')
        for _ in range(8):
            state = self.report(state, links=[], scan={'loading': True})
        self.assertEqual(state['state'], 'running')
        for _ in range(2):
            state = self.report(state, links=['https://xueqiu.com/123/2'], scan={'explicit_end': True})
        self.assertEqual(state['phase'], 'capture')
        self.assertEqual(state['discovered'], 2)

    def test_rescan_retains_saved_articles_and_cursor(self):
        state = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 500})['id'], 'resume')
        state = self.report(state, links=['https://xueqiu.com/123/1'])
        state = batch.control(state['id'], 'finish-scan')
        state = self.report(state, html=POST)
        state = batch.control(state['id'], 'rescan')
        self.assertEqual(state['processed'], 1)
        self.assertEqual(state['saved'], 1)
        self.assertEqual(state['phase'], 'scan')
        self.assertTrue(state['auto_after'])
        state = self.report(state, links=['https://xueqiu.com/123/1','https://xueqiu.com/123/2'])
        self.assertEqual(state['discovered'], 2)

    def test_new_task_skips_saved_articles_but_not_failures(self):
        first = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 2})['id'], 'resume')
        first = self.report(first, links=['https://xueqiu.com/123/1', 'https://xueqiu.com/123/2'])
        first = self.report(first, html=POST)
        batch.control(first['id'], 'skip')
        second = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 500})['id'], 'resume')
        second = self.report(second, links=['https://xueqiu.com/123/1', 'https://xueqiu.com/123/2'])
        self.assertEqual(second['skipped_existing'], 1)
        self.assertEqual(second['discovered'], 1)
        self.assertEqual(batch.load(second['id'])['urls'], ['https://xueqiu.com/123/2'])

    def test_www_and_bare_host_are_same_article(self):
        first = batch.control(batch.create({'url': 'https://www.xueqiu.com/u/123', 'limit': 1})['id'], 'resume')
        first = self.report(first, links=['https://www.xueqiu.com/123/1'])
        self.report(first, html=POST)
        second = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 1})['id'], 'resume')
        second = self.report(second, links=['https://xueqiu.com/123/1'])
        self.assertEqual(second['discovered'], 0)
        self.assertEqual(second['skipped_existing'], 1)

    def test_duplicate_is_rechecked_before_capture(self):
        first = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 1})['id'], 'resume')
        second = batch.control(batch.create({'url': 'https://xueqiu.com/u/123', 'limit': 1})['id'], 'resume')
        first = self.report(first, links=['https://xueqiu.com/123/1'])
        second = self.report(second, links=['https://xueqiu.com/123/1'])
        first = self.report(first, html=POST)
        second = self.report(second, html=POST)
        self.assertEqual(first['saved'], 1)
        self.assertEqual(second['saved'], 0)
        self.assertEqual(second['skipped_existing'], 1)


if __name__ == '__main__':
    unittest.main()
