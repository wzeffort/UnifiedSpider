import tempfile
import unittest
from pathlib import Path
from storage import save, read
from author_directory import resolve_directory
from article_metadata import extract_account_name


class DirectoryTests(unittest.TestCase):
    def test_rename_preserves_files_and_identity_with_duplicate_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'xueqiu_1';old.mkdir()
            (old/'article.md').write_bytes(b'original')
            save(old/'export.json',{'ready':True})
            source={'platform':'xueqiu','owner':'1','name':'行中衡'}
            path=resolve_directory(root,source,'xueqiu_1')
            self.assertEqual(path.name,'雪球_行中衡')
            self.assertEqual((path/'article.md').read_bytes(),b'original')
            self.assertFalse(old.exists())
            self.assertEqual(read(path/'export.json')['author_key'],'xueqiu_1')
            self.assertEqual(resolve_directory(root,{**source,'name':'新名字'},'xueqiu_1'),path)
            other=resolve_directory(root,{**source,'owner':'2'},'xueqiu_2')
            self.assertNotEqual(path,other)

    def test_only_target_account_link_names_are_used(self):
        html='<a href="/99">转载作者</a><a href="https://evil.test/u/1">错误</a><a href="/u/1">@行中衡</a>'
        self.assertEqual(extract_account_name(html,{'platform':'xueqiu','owner':'1'}),'行中衡')
        self.assertIsNone(extract_account_name(html,{'platform':'xueqiu','owner':'2'}))

    def test_name_cannot_escape_export_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=resolve_directory(root,{'platform':'xueqiu','name':'../../坏\\名'},'xueqiu_1')
            self.assertEqual(path.parent,root)


if __name__=='__main__':unittest.main()
