import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from .helpers import make_bundle, make_env
from rpiota import state, web


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.env = make_env(self.dir / "device")
        self.env.model.write_bytes(b"Test Board Rev 1.0\0")
        self.bundle = make_bundle(self.dir)[0].read_bytes()
        static = Path(__file__).resolve().parents[1] / "web"
        self.server = web.make_server(self.env, "127.0.0.1", 0, static)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        return response.status, response.read()

    def api(self, method, path, body=None):
        status, data = self.request(method, path, body)
        return status, json.loads(data)

    def incoming(self):
        return sorted(p.name for p in self.env.incoming.iterdir())

    def test_status_defaults(self):
        status, data = self.api("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"state": "idle", "error": None, "version": "1.0",
                                "slot": "a", "target": None, "uploaded": None,
                                "progress": None, "device": socket.gethostname(),
                                "board": "Test Board Rev 1.0", "cpu": "unknown",
                                "gpu": "unknown", "ram": "unknown"})

    def test_status_shows_progress(self):
        progress = {"part": "system", "percent": 40}
        state.write(self.env, "writing", target="2.0", progress=progress)
        self.assertEqual(self.api("GET", "/api/status")[1]["progress"], progress)

    def test_upload_then_apply(self):
        status, data = self.api("PUT", "/api/upload", self.bundle)
        self.assertEqual((status, data), (202, {"ok": True, "version": "2.0"}))
        self.assertEqual(self.env.upload.read_bytes(), self.bundle)
        self.assertEqual(self.incoming(), ["upload.ota"])  # 上傳不會觸發套用
        self.assertEqual(self.api("GET", "/api/status")[1]["uploaded"], "2.0")
        status, data = self.api("POST", "/api/apply")
        self.assertEqual((status, data), (202, {"ok": True}))
        self.assertEqual(self.incoming(), ["pending.ota"])
        current = self.api("GET", "/api/status")[1]
        self.assertEqual((current["state"], current["target"]), ("verifying", "2.0"))

    def test_apply_without_upload(self):
        self.assertEqual(self.api("POST", "/api/apply"),
                         (409, {"ok": False, "error": "no_upload"}))

    def test_rejects_non_bundle(self):
        self.assertEqual(self.api("PUT", "/api/upload", b"junk" * 1000),
                         (400, {"ok": False, "error": "bad_bundle"}))
        self.assertEqual(self.incoming(), [])

    def test_busy(self):
        busy = (409, {"ok": False, "error": "busy"})
        for name in ("verifying", "writing", "pending"):
            with self.subTest(name):
                state.write(self.env, name)
                self.env.upload.write_bytes(self.bundle)
                self.assertEqual(self.api("PUT", "/api/upload", self.bundle), busy)
                self.assertEqual(self.api("POST", "/api/apply"), busy)
                self.assertEqual(self.incoming(), ["upload.ota"])
        state.write(self.env, "failed", error="bad_hash")
        self.env.pending.write_bytes(b"x")
        self.assertEqual(self.api("PUT", "/api/upload", self.bundle), busy)
        self.assertEqual(self.api("POST", "/api/apply"), busy)
        self.assertEqual(self.env.pending.read_bytes(), b"x")

    def test_large_rejected_upload_still_gets_reply(self):
        state.write(self.env, "pending")
        self.assertEqual(self.api("PUT", "/api/upload", b"x" * (8 << 20))[0], 409)

    def raw_upload(self, length, body):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.sendall(b"PUT /api/upload HTTP/1.1\r\nHost: x\r\nContent-Length: "
                     + length + b"\r\n\r\n" + body)
        return sock

    def test_short_body_leaves_nothing(self):
        sock = self.raw_upload(str(len(self.bundle)).encode(), self.bundle[:1000])
        for _ in range(100):
            if self.env.part.exists():
                break
            time.sleep(0.02)
        self.assertEqual(self.api("PUT", "/api/upload", self.bundle)[0], 409)  # 另一個上傳中
        sock.shutdown(socket.SHUT_WR)
        sock.recv(4096)
        sock.close()
        self.assertEqual(self.incoming(), [])

    def test_bad_length(self):
        for length in (b"abc", b"0", b"-5"):
            with self.subTest(length):
                sock = self.raw_upload(length, b"")
                self.assertIn(b" 411 ", sock.recv(4096))
                sock.close()

    def test_no_space(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10)):
            self.assertEqual(self.api("PUT", "/api/upload", self.bundle),
                             (507, {"ok": False, "error": "no_space"}))
        self.assertEqual(self.incoming(), [])

    def test_leftover_part_removed_on_start(self):
        self.env.part.write_bytes(b"x")
        web.make_server(self.env, "127.0.0.1", 0, self.dir).server_close()
        self.assertFalse(self.env.part.exists())

    def test_static_files(self):
        for path in ("/", "/pure-min.css", "/app.js"):
            status, data = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(data)

    def test_unknown_and_traversal_paths(self):
        for path in ("/../rpiota/env.py", "/index.html/../x", "/nope"):
            self.assertEqual(self.request("GET", path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
