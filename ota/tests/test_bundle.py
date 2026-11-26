import json
import tempfile
import unittest
from pathlib import Path

from .helpers import make_bundle, rewrite_tar
from rpiota import bundle


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path, _, _ = make_bundle(self.dir)

    def assert_code(self, path, code):
        with self.assertRaises(bundle.UpdateError) as ctx:
            bundle.verify(path)
        self.assertEqual(ctx.exception.code, code)

    def edit(self, fn):
        return rewrite_tar(self.path, self.dir / "edited.ota", fn)

    def edit_manifest(self, **changes):
        def fn(members):
            manifest = json.loads(members[0][1])
            manifest.update(changes)
            return [("manifest.json", json.dumps(manifest).encode())] + members[1:]
        return self.edit(fn)

    def test_pack_then_verify(self):
        manifest = bundle.verify(self.path)
        self.assertEqual(
            (manifest.version, manifest.device_class, manifest.source_date_epoch),
            ("2.0", "cm4", 2000))
        self.assertEqual(manifest.boot.raw_size, 4 * 4096)
        self.assertEqual(bundle.read_manifest(self.path), manifest)

    def test_tampered_image(self):
        path = self.edit(lambda m: m[:2] + [(m[2][0], m[2][1] + b"x")])
        self.assert_code(path, "bad_hash")

    def test_extra_or_traversal_member(self):
        self.assert_code(self.edit(lambda m: m + [("../x", b"x")]), "bad_bundle")

    def test_wrong_member_order(self):
        self.assert_code(self.edit(lambda m: [m[0], m[2], m[1]]), "bad_bundle")

    def test_missing_member(self):
        self.assert_code(self.edit(lambda m: m[:2]), "bad_bundle")

    def test_not_a_tar(self):
        junk = self.dir / "junk"
        junk.write_bytes(b"not a tar" * 500)
        self.assert_code(junk, "bad_bundle")

    def test_oversized_manifest(self):
        path = self.edit(lambda m: [(m[0][0], m[0][1] + b" " * 70000)] + m[1:])
        self.assert_code(path, "bad_bundle")

    def test_bad_manifest_fields(self):
        for changes in ({"format": 2}, {"version": "<b>"}, {"source_date_epoch": "9"},
                        {"boot": None}, {"device_class": 4}):
            with self.subTest(changes):
                self.assert_code(self.edit_manifest(**changes), "bad_bundle")

    def test_pack_rejects_bad_version(self):
        with self.assertRaises(bundle.UpdateError):
            make_bundle(self.dir, version="a b", name="bad.ota")
        self.assertFalse((self.dir / "bad.ota").exists())


if __name__ == "__main__":
    unittest.main()
