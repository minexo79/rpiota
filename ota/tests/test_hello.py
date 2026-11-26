import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import hello  # noqa: E402


class HelloTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "version"

    def run_hello(self, count=1):
        lines, sleeps = [], []
        hello.run(self.path, count=count, sleep=sleeps.append, out=lines.append)
        return lines, sleeps

    def test_hello_prints_version_every_three_seconds(self):
        self.path.write_text("1.0\n", encoding="utf-8")
        self.assertEqual(self.run_hello(2), (["Hello OTA 1.0"] * 2, [3, 3]))

    def test_missing_version_file_prints_unknown(self):
        self.assertEqual(self.run_hello()[0], ["Hello OTA unknown"])

    def test_blank_version_file_prints_unknown(self):
        self.path.write_text("\n", encoding="utf-8")
        self.assertEqual(self.run_hello()[0], ["Hello OTA unknown"])

    def test_default_version_file(self):
        self.assertEqual(hello.VERSION_FILE, Path("/etc/rpiota/version"))

    def test_loads_without_rpiota(self):
        copy = Path(self.tmp.name) / "hello.py"
        shutil.copy(hello.__file__, copy)
        subprocess.run(
            [sys.executable, "-I", "-B", "-c",
             "import runpy, sys; runpy.run_path(sys.argv[1])", str(copy)],
            check=True, cwd=self.tmp.name)


if __name__ == "__main__":
    unittest.main()
