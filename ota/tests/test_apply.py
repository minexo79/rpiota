import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .helpers import BLOCK, make_bundle, make_env, rewrite_tar
from rpiota import apply, state


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.env = make_env(self.dir / "device")
        self.other = self.env.slot_dir / "other"
        self.active = self.env.slot_dir / "active"

    def stage(self, **options):
        path, boot, system = make_bundle(self.dir, **options)
        path.replace(self.env.pending)
        return boot, system

    def assert_failed(self, code):
        current = state.read(self.env)
        self.assertEqual((current["state"], current["error"]), ("failed", code))
        self.assertEqual(self.env.calls, [])
        self.assertFalse(self.env.pending.exists())

    def contents(self):
        return [(d / p).read_bytes() for d in (self.active, self.other)
                for p in ("boot", "system")]

    def test_success_writes_other_slot(self):
        before = (self.active / "system").read_bytes()
        boot, system = self.stage()
        apply.apply(self.env)
        self.assertEqual((self.other / "boot").read_bytes()[:len(boot)], boot)
        self.assertEqual((self.other / "system").read_bytes()[:len(system)], system)
        self.assertEqual((self.active / "system").read_bytes(), before)
        current = state.read(self.env)
        self.assertEqual((current["state"], current["target"]), ("pending", "2.0"))
        self.assertTrue(current["slot_dev"].endswith("system"))
        self.assertEqual(self.env.calls[-1], ["reboot", "0 tryboot"])
        self.assertFalse(self.env.pending.exists())

    def test_reports_progress(self):
        seen, write = [], state.write

        def spy(env, name, *args, **kwargs):
            if kwargs.get("progress"):
                seen.append(kwargs["progress"])
            write(env, name, *args, **kwargs)

        self.stage()
        with mock.patch.object(state, "write", spy):
            apply.apply(self.env)
        for part in ("boot", "system"):
            percents = [p["percent"] for p in seen if p["part"] == part]
            self.assertEqual((percents[0], percents[-1]), (0, 100), part)
            self.assertEqual(percents, sorted(set(percents)), part)
        self.assertNotIn("progress", state.read(self.env))

    def test_rejects(self):
        before = self.contents()
        self.stage(device_class="pi5")
        apply.apply(self.env)
        self.assert_failed("wrong_device")
        self.assertEqual(self.contents(), before)
        self.assertTrue(self.stamp("b").exists())

    def stamp(self, slot):
        return self.env.persistent_slots / f"system_{slot}" / "var" / ".updated"

    def test_older_and_same_version_install(self):
        # make_env 的目前映像 epoch 是 1000
        for epoch in (500, 1000):
            with self.subTest(epoch):
                state.write(self.env, "idle")
                self.stage(epoch=epoch)
                apply.apply(self.env)
                self.assertEqual(state.read(self.env)["state"], "pending")

    def test_resets_target_var(self):
        self.stage()
        apply.apply(self.env)
        self.assertFalse(self.stamp("b").exists())
        self.assertTrue(self.stamp("a").exists())

    def test_missing_stamp_is_ok(self):
        self.stamp("b").unlink()
        self.stage()
        apply.apply(self.env)
        self.assertEqual(state.read(self.env)["state"], "pending")

    def assert_nothing_written(self):
        before = self.contents()
        self.stage()
        apply.apply(self.env)
        self.assert_failed("write_failed")
        self.assertEqual(self.contents(), before)
        self.assertTrue(self.stamp("a").exists())

    def test_unknown_target_slot_writes_nothing(self):
        (self.env.label_dir / "system_b").unlink()
        self.assert_nothing_written()

    def test_missing_var_directory_writes_nothing(self):
        self.stamp("b").unlink()
        self.stamp("b").parent.rmdir()
        self.assert_nothing_written()

    def test_stamp_removal_failure_writes_nothing(self):
        self.stamp("b").unlink()
        self.stamp("b").mkdir()
        self.assert_nothing_written()

    def test_bad_hash(self):
        self.stage()
        broken = rewrite_tar(self.env.pending, self.dir / "broken",
                             lambda m: m[:2] + [(m[2][0], b"x")])
        broken.replace(self.env.pending)
        apply.apply(self.env)
        self.assert_failed("bad_hash")

    def test_too_large(self):
        (self.other / "system").write_bytes(b"s" * BLOCK)
        before = self.contents()
        self.stage()
        apply.apply(self.env)
        self.assert_failed("too_large")
        self.assertEqual(self.contents(), before)

    def test_write_error(self):
        # 雜湊正確但內容不是 sparse 映像
        self.stage()
        junk = subprocess.run(["zstd", "-q"], input=b"j" * 100, capture_output=True,
                              check=True).stdout

        def edit(members):
            manifest = json.loads(members[0][1])
            manifest["system"]["sha256"] = hashlib.sha256(junk).hexdigest()
            return [("manifest.json", json.dumps(manifest).encode()), members[1],
                    (members[2][0], junk)]

        rewrite_tar(self.env.pending, self.dir / "bad", edit).replace(self.env.pending)
        apply.apply(self.env)
        self.assert_failed("write_failed")

    def test_missing_device_is_not_created(self):
        (self.other / "boot").unlink()
        self.stage()
        apply.apply(self.env)
        self.assert_failed("write_failed")
        self.assertFalse((self.other / "boot").exists())

    def test_never_writes_active_slot(self):
        self.env.slot_dir.joinpath("other").rename(self.dir / "unused")
        self.env.slot_dir.joinpath("other").mkdir()
        # 模擬 other 與 active 指到同一個裝置
        for part in ("boot", "system"):
            os.link(self.active / part, self.other / part)
        before = self.contents()
        self.stage()
        apply.apply(self.env)
        self.assert_failed("write_failed")
        self.assertEqual(self.contents(), before)

    def test_reboot_failure(self):
        def run(args):
            raise OSError("no reboot")
        self.env.run = run
        self.stage()
        apply.apply(self.env)
        current = state.read(self.env)
        self.assertEqual((current["state"], current["error"]), ("failed", "write_failed"))

    def test_busy_while_pending(self):
        state.write(self.env, "pending", target="1.5", slot_dev="/dev/x")
        before = self.contents()
        self.stage()
        apply.apply(self.env)
        self.assertEqual(state.read(self.env)["state"], "pending")
        self.assertEqual(state.read(self.env)["target"], "1.5")
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.env.calls, [])
        self.assertFalse(self.env.pending.exists())

    def test_nothing_to_do(self):
        apply.apply(self.env)
        self.assertEqual(state.read(self.env)["state"], "idle")


if __name__ == "__main__":
    unittest.main()
