import os
import tempfile
import unittest

from .helpers import make_env
from rpiota import commit, state


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = make_env(self.tmp.name)
        self.now = 0.0
        self.here = os.path.realpath(self.env.slot_dir / "active" / "system")
        self.healthy = lambda unit: True
        base = self.env.run

        def run(args):
            out = base(args)
            if args[:2] == ["systemctl", "is-active"] and not self.healthy(args[-1]):
                raise OSError("inactive")
            return out

        self.env.run = run

    def sleep(self, seconds):
        self.now += seconds

    def kwargs(self):
        return {"timeout_s": 30, "interval_s": 5, "sleep": self.sleep,
                "clock": lambda: self.now}

    def pending(self, slot_dev=None, error=None):
        state.write(self.env, "pending", error=error, target="2.0",
                    slot_dev=slot_dev or self.here)

    def result(self):
        current = state.read(self.env)
        return current["state"], current["error"]

    def test_commit_writes_autoboot(self):
        self.pending()
        self.assertEqual(commit.commit(self.env, **self.kwargs()), "committed")
        self.assertEqual(self.env.autoboot.read_text(), "[all]\nboot_partition=3\n")
        self.assertEqual(self.result(), ("committed", None))

    def test_unhealthy_reboots_without_commit(self):
        self.healthy = lambda unit: unit != "web.service"
        self.pending()
        self.assertEqual(commit.commit(self.env, **self.kwargs()), "pending")
        self.assertEqual(self.env.autoboot.read_text(), "old\n")
        self.assertEqual(self.env.calls[-1], ["reboot"])
        self.assertEqual(self.result(), ("pending", "health_failed"))

    def test_booted_old_slot(self):
        for error, expected in ((None, "rolled_back"), ("health_failed", "health_failed")):
            with self.subTest(error):
                self.pending("/dev/elsewhere", error)
                self.assertEqual(commit.commit(self.env, **self.kwargs()), "rolled_back")
                self.assertEqual(self.result(), ("rolled_back", expected))
                self.assertEqual(self.env.autoboot.read_text(), "old\n")

    def test_interrupted_write(self):
        for previous in ("verifying", "writing"):
            with self.subTest(previous):
                state.write(self.env, previous, target="2.0")
                for file in (self.env.pending, self.env.part):
                    file.write_bytes(b"x")
                commit.commit(self.env, **self.kwargs())
                self.assertEqual(self.result(), ("failed", "interrupted"))
                self.assertFalse(self.env.pending.exists())
                self.assertFalse(self.env.part.exists())

    def test_empty_or_missing_health_list_is_unhealthy(self):
        units = self.env.conf_dir / "health.units"
        for content in ("\n# 空的\n", None):
            with self.subTest(content):
                if content is None:
                    units.unlink()
                else:
                    units.write_text(content, encoding="utf-8")
                self.pending()
                self.assertEqual(commit.commit(self.env, **self.kwargs()), "pending")
                self.assertEqual(self.env.autoboot.read_text(), "old\n")

    def test_flapping_unit_not_committed(self):
        checks = []

        def healthy(unit):
            checks.append(unit)
            return len(checks) % 4 in (1, 2)  # 一輪成功、一輪失敗

        self.healthy = healthy
        self.pending()
        self.assertEqual(commit.commit(self.env, **self.kwargs()), "pending")
        self.assertEqual(self.env.autoboot.read_text(), "old\n")

    def test_idle_does_nothing(self):
        self.assertEqual(commit.commit(self.env, **self.kwargs()), "idle")
        self.assertEqual(self.env.calls, [])

    def test_main_exit_codes(self):
        def broken(args):
            if args[0] == "rpi-slot-tryboot":
                raise OSError("broken")
            return ""

        self.env.run = broken
        self.pending()
        # 在目標 slot 但確認不了 → 非零，讓 systemd 重開
        self.assertEqual(commit.main(self.env, **self.kwargs()), 1)
        # 舊 slot 上任何錯誤都不能非零，否則無限重開
        self.pending("/dev/elsewhere")
        (self.env.ota_dir / "state.json.tmp").mkdir()
        self.assertEqual(commit.main(self.env, **self.kwargs()), 0)

    def fail_tryboot(self):
        base = self.env.run

        def run(args):
            if args[0] == "rpi-slot-tryboot":
                raise OSError("broken")
            return base(args)

        self.env.run = run

    def test_commit_failure_is_reported_after_rollback(self):
        self.fail_tryboot()
        self.pending()
        self.assertEqual(commit.main(self.env, **self.kwargs()), 1)
        self.assertEqual(self.result(), ("pending", "commit_failed"))
        # 重開後回到舊 slot：目標 slot 不是目前開機的那個
        current = state.read(self.env)
        self.pending("/dev/elsewhere", current["error"])
        commit.main(self.env, **self.kwargs())
        self.assertEqual(self.result(), ("rolled_back", "commit_failed"))

    def test_commit_failure_still_reboots_if_reason_cannot_be_saved(self):
        self.fail_tryboot()
        self.pending()
        (self.env.ota_dir / "state.json.tmp").mkdir()
        self.assertEqual(commit.main(self.env, **self.kwargs()), 1)

    def test_failed_reboot_keeps_health_failed(self):
        def run(args):
            raise OSError("broken")

        self.env.run = run
        self.pending()
        self.assertEqual(commit.main(self.env, **self.kwargs()), 1)
        self.assertEqual(self.result(), ("pending", "health_failed"))


if __name__ == "__main__":
    unittest.main()
