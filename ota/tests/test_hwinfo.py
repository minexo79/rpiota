import subprocess
import tempfile
import unittest

from .helpers import make_env
from rpiota import hwinfo

LSCPU = """\
Architecture:            aarch64
  Byte Order:            Little Endian
CPU(s):                  4
Vendor ID:               ARM
  Model name:            Cortex-A72
    Model:               3
    CPU max MHz:         1500.0000
    CPU min MHz:         600.0000
NUMA node0 CPU(s):       0-3
"""


class HardwareInfoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = make_env(tmp.name)
        self.env.run = lambda args: LSCPU

    def test_reads_cm4(self):
        self.env.model.write_bytes(b"Raspberry Pi Compute Module 4 Rev 1.1\0")
        self.env.compatible.write_bytes(
            b"raspberrypi,4-compute-module\0brcm,bcm2711\0")
        self.env.meminfo.write_text("MemTotal:        3885396 kB\nMemFree: 1 kB\n")
        self.assertEqual(hwinfo.read(self.env), {
            "board": "Raspberry Pi Compute Module 4 Rev 1.1",
            "cpu": "Cortex-A72 × 4 @ 1.50 GHz (aarch64)",
            "gpu": "VideoCore VI",
            "ram": "3.7 GiB"})

    def test_unreadable_sources_are_unknown(self):
        def fail(args):
            raise subprocess.CalledProcessError(1, args)

        self.env.run = fail
        self.assertEqual(hwinfo.read(self.env),
                         dict.fromkeys(("board", "cpu", "gpu", "ram"), "unknown"))

    def test_missing_lscpu(self):
        def fail(args):
            raise FileNotFoundError(args[0])

        self.env.run = fail
        self.assertEqual(hwinfo.read(self.env)["cpu"], "unknown")

    def test_cpu_without_max_clock(self):
        self.env.run = lambda args: LSCPU.replace("CPU max MHz", "other")
        self.assertEqual(hwinfo.read(self.env)["cpu"], "Cortex-A72 × 4 (aarch64)")

    def test_cpu_without_model_name(self):
        self.env.run = lambda args: LSCPU.replace("Model name", "other")
        self.assertEqual(hwinfo.read(self.env)["cpu"], "unknown")

    def test_unrecognised_soc(self):
        self.env.compatible.write_bytes(b"vendor,board\0vendor,soc\0")
        self.assertEqual(hwinfo.read(self.env)["gpu"], "unknown")


if __name__ == "__main__":
    unittest.main()
