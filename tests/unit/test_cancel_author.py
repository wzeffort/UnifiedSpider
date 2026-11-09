import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import article_store
import author_batch as batch
import author_pipeline
from tests.unit.test_author_batch import POST


class CancelAuthor(unittest.TestCase):
    def test_cancel_exports_and_retains_dedup_rejects_late_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('author_batch.job_folder',side_effect=lambda key:root/key), patch('download_settings.settings',return_value={'mode':'folder','folder':str(root/'out')}), patch('mineru_client.recognize') as ocr, patch('rag_assets.download') as download:
                task=batch.create({'url':'https://xueqiu.com/u/123','auto_after':True})
                folder=root/task['id']
                page={'url':'https://xueqiu.com/123/1','title':'已采集','text':'已有正文','markdown':'已有正文','images':[]}
                article_store.put(folder,page)
                data=batch.load(task['id']);data.update(state='running',phase='capture',urls=[page['url'],'https://xueqiu.com/123/2'],cursor=1)
                batch.persist(data)
                before=(folder/'articles.sqlite3').read_bytes()
                state=batch.control(task['id'],'cancel')
                deadline=time.monotonic()+8
                while task['id'] in author_pipeline.PENDING and time.monotonic()<deadline:time.sleep(.05)
                self.assertNotIn(task['id'],author_pipeline.PENDING)
                data=batch.load(task['id'])
                self.assertEqual(data['state'],'cancelled')
                self.assertEqual(data['auto_state'],'done')
                self.assertEqual(data['last_export']['author_documents_count'],1)
                batch.report(task['id'],{'revision':data['revision'],'url':data['urls'][1],'html':POST})
                self.assertEqual((folder/'articles.sqlite3').read_bytes(),before)
                new=batch.create({'url':'https://xueqiu.com/u/123'})
                self.assertIn(page['url'],batch.load(new['id'])['known_saved'])
                author_pipeline.recognize_article(task['id'],page['url'])
                ocr.assert_not_called();download.assert_not_called()
                with self.assertRaises(ValueError):batch.control(task['id'],'resume')
                self.assertEqual(batch.control(task['id'],'cancel')['state'],'cancelled')


if __name__=='__main__':unittest.main()
