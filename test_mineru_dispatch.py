import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import mineru_dispatch as d
import mineru_client as m
import mineru_selfhost as s


class DispatchTests(unittest.TestCase):
    def test_two_lanes_deduplicate_and_cache(self):
        barrier = threading.Barrier(3)
        release = threading.Event()
        calls = []
        def worker(path, timeout):
            calls.append(path.name)
            barrier.wait(timeout=5)
            release.wait(timeout=5)
            return {'text': path.name}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root/'a.png', root/'b.png'
            a.write_bytes(b'a'); b.write_bytes(b'b')
            with patch.object(m, 'CACHE', root/'cache'), patch.object(m, 'recognize_official', side_effect=worker), patch.object(s, 'recognize', side_effect=worker):
                first = d.submit(a)
                self.assertIs(d.submit(a), first)
                second = d.submit(b)
                try:
                    barrier.wait(timeout=5)
                    self.assertEqual(d.PENDING, {'local': 1, 'official': 1})
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5), {'text':'a.png'})
                second.result(timeout=5)
                # Wait for callbacks without touching production queues.
                for pool in d.POOLS.values(): pool.submit(lambda: None).result(timeout=5)
                self.assertEqual(d.submit(a).result(), {'text':'a.png'})
                self.assertEqual(len(calls), 2)
                self.assertEqual(d.PENDING, {'local':0, 'official':0})
                self.assertFalse(d.INFLIGHT)


if __name__ == '__main__': unittest.main()
