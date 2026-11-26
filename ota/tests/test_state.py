import tempfile
import unittest

from .helpers import make_env
from rpiota import state


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = make_env(self.tmp.name)

    def test_state_default_and_roundtrip(self):
        self.assertEqual(state.read(self.env)["state"], "idle")
        state.write(self.env, "pending", target="2.0", slot_dev="/dev/x")
        self.assertEqual(
            state.read(self.env),
            {"state": "pending", "error": None, "target": "2.0", "slot_dev": "/dev/x"})

    def test_corrupt_state_reads_as_idle(self):
        (self.env.ota_dir / "state.json").write_text("{")
        self.assertEqual(state.read(self.env)["state"], "idle")


if __name__ == "__main__":
    unittest.main()
