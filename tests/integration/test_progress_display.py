import json
import unittest
from playwright.sync_api import sync_playwright, expect


class ProgressDisplay(unittest.TestCase):
    def test_stage_progress_buttons_and_disconnect(self):
        task = {'id': 'ui-stage', 'source': {'platform': 'xueqiu', 'owner': '123', 'url': 'https://xueqiu.com/u/123'},
                'created': '2026-11-06', 'state': 'needs_user', 'phase': 'scan', 'saved': 0, 'discovered': 126,
                'processed': 0, 'revision': 1, 'skipped_existing': 67, 'auto_after': True,
                'auto_state': None, 'message': '列表加载停滞', 'enrichment': {'state': 'idle'}, 'last_export': None}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            posts, errors = [], []
            page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/api/authors', lambda r: r.fulfill(json=[task]))
            page.route('**/api/jobs', lambda r: r.fulfill(json=[]))
            page.route('**/api/result/ui-stage', lambda r: r.fulfill(json={'pages':[{'images':[{'ocr':{'text':'ok'}},{'url':'pending'}]}]}))
            page.goto('http://127.0.0.1:18765/')
            summary=page.locator('#authorOverview')
            expect(summary).to_contain_text('当前未运行采集')
            expect(page.locator('#authorStart')).to_be_disabled()
            expect(page.locator('#authorPauseAll')).to_be_disabled()
            expect(page.get_by_role('button',name='继续',exact=True)).to_be_enabled()
            expect(page.locator('[data-stage-progress] progress')).to_have_attribute('value','0')
            task.update(state='running')
            page.reload()
            expect(summary).to_contain_text('正在跑任务')
            expect(page.locator('#authorPauseAll')).to_be_enabled()
            expect(page.locator('#authorLimit')).to_be_disabled()
            expect(page.locator('[data-stage-progress] progress')).not_to_have_attribute('value')
            task.update(phase='capture',processed=63,saved=63)
            page.reload()
            expect(page.locator('[data-stage-progress] progress')).to_have_attribute('value','50')
            task.update(state='finished',auto_state='recognizing',enrichment={'state':'running'})
            page.reload()
            expect(summary).to_contain_text('正文采集当前未运行')
            expect(page.locator('[data-stage-progress]')).to_contain_text('图片已识别 1 / 2 张')
            expect(page.locator('#authorPauseAll')).to_be_disabled()
            expect(page.locator('#authorStart')).to_be_disabled()
            task.update(auto_state='done',enrichment={'state':'finished'},last_export={'documents_count':63,'revision':1,'folder':'D:/fixture'})
            page.reload()
            expect(summary).to_contain_text('当前没有任务运行')
            expect(page.locator('#authorStart')).to_be_enabled()
            expect(page.locator('#authorLimit')).to_be_enabled()
            page.route('**/api/authors',lambda r:r.fulfill(status=503,json={'error':'offline'}))
            page.reload()
            expect(summary).to_contain_text('无法确认任务状态')
            expect(page.locator('#authorStart')).to_be_disabled()
            self.assertEqual(posts,[])
            self.assertEqual(errors,[])
            browser.close()

    def test_readonly_counts_and_export_snapshot(self):
        task = {'id': 'progress-fixture', 'source': {'platform': 'xueqiu', 'owner': '123', 'url': 'https://xueqiu.com/u/123'},
                'created': '2026-11-05', 'state': 'running', 'phase': 'capture', 'saved': 71, 'discovered': 176,
                'revision': 80, 'skipped_existing': 26, 'auto_after': True, 'auto_state': 'streaming',
                'message': '已保存 71 篇。', 'enrichment': {'state': 'running', 'done': 0}, 'last_export': None}
        result = {'pages': [{'images': [{'file': 'one.png', 'ocr': {'text': '文字'}}]},
                            {'images': [{'url': 'pending'}, {'file': 'bad.png', 'error': '超时'}]}]}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            posts, downloads, errors = [], [], []
            page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
            page.on('download', lambda d: downloads.append(d))
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/api/authors', lambda r: r.fulfill(json=[task]))
            page.route('**/api/result/progress-fixture', lambda r: r.fulfill(json=result))
            page.goto('http://127.0.0.1:18765/?view=progress')
            page.get_by_text('正文已入库：71 篇', exact=False).wait_for()
            metric = page.locator('[data-image-progress]')
            metric.get_by_text('已识别 1 / 3 张', exact=False).wait_for()
            self.assertIn('待处理 1 张，异常 1 张', metric.inner_text())
            self.assertIn('有图文章已完成 1 / 2 篇', metric.inner_text())
            self.assertIn('覆盖已入库 2 篇', metric.inner_text())
            self.assertIn('已导出：0 篇', page.locator('[data-export-progress]').inner_text())
            self.assertNotIn('已处理 0 篇', page.locator('#authorTasks').inner_text())
            self.assertFalse(page.get_by_role('button', name='暂停', exact=True).is_visible())
            task['last_export'] = {'documents_count': 26, 'revision': 34, 'exported_at': '2026-11-05T08:21:48+00:00', 'folder': 'D:/fixture'}
            page.wait_for_timeout(5500)
            self.assertIn('已导出：26 篇', page.locator('[data-export-progress]').inner_text())
            self.assertIn('上次导出快照', page.locator('[data-export-progress]').inner_text())
            self.assertEqual(posts, [])
            self.assertEqual(downloads, [])
            self.assertEqual(errors, [])
            browser.close()


if __name__ == '__main__':
    unittest.main()
