import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import BLOCK, sparse_bytes
from rpiota import sparse


class SparseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def apply(self, data, limit=16 * BLOCK):
        out = io.BytesIO(b"\xaa" * (16 * BLOCK))
        size = sparse.write(io.BytesIO(data), out, limit)
        return size, out.getvalue()

    def test_raw_fill_and_skip(self):
        raw = bytes(range(256)) * 16
        size, out = self.apply(sparse_bytes(
            [("raw", raw), ("skip", 1), ("fill", b"wxyz", 2)]))
        self.assertEqual(size, 4 * BLOCK)
        self.assertEqual(out[:BLOCK], raw)
        self.assertEqual(out[BLOCK:2 * BLOCK], b"\xaa" * BLOCK)
        self.assertEqual(out[2 * BLOCK:4 * BLOCK], b"wxyz" * (BLOCK // 2))

    def test_reports_progress(self):
        seen = []
        sparse.write(io.BytesIO(sparse_bytes([("raw", b"a" * BLOCK), ("skip", 3)])),
                     io.BytesIO(), 16 * BLOCK, lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(BLOCK, 4 * BLOCK), (4 * BLOCK, 4 * BLOCK)])

    def test_large_chunks_are_written_in_steps(self):
        seen = []
        out = io.BytesIO()
        data = sparse_bytes([("raw", b"a" * (3 * BLOCK)), ("fill", b"wxyz", 3)])
        with mock.patch.object(sparse, "STEP", 2 * BLOCK):
            sparse.write(io.BytesIO(data), out, 16 * BLOCK,
                         lambda done, total: seen.append(done // BLOCK))
        self.assertEqual(seen, [2, 3, 5, 6])
        self.assertEqual(out.getvalue(), b"a" * (3 * BLOCK) + b"wxyz" * (3 * BLOCK // 4))

    def test_raw_size_from_header(self):
        path = Path(self.tmp.name) / "x.sparse"
        path.write_bytes(sparse_bytes([("skip", 5)]))
        self.assertEqual(sparse.raw_size(path), 5 * BLOCK)

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            self.apply(b"\0" * 64)

    def test_truncated(self):
        with self.assertRaises(ValueError):
            self.apply(sparse_bytes([("raw", b"a" * BLOCK)])[:-1])

    def test_exceeds_limit(self):
        with self.assertRaises(ValueError):
            self.apply(sparse_bytes([("skip", 3)]), limit=2 * BLOCK)

    def test_chunks_must_match_total_blocks(self):
        with self.assertRaises(ValueError):
            self.apply(sparse_bytes([("skip", 1)], blocks=2))


if __name__ == "__main__":
    unittest.main()
