"""更新網頁（非 root）。沒有任何身分驗證，只適合實驗網路。

PUT /api/upload ─> upload.part ─(收滿且是更新包)─> upload.ota
POST /api/apply ─> upload.ota 改名 pending.ota ─> apply 服務接手
GET /api/status ─> 硬體資訊、裝置名稱、目前版本、slot、更新狀態
"""
import argparse
import errno
import json
import logging
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import bundle, hwinfo, state
from .env import Env

CHUNK = 1 << 20
BUSY = ("verifying", "writing", "pending")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/pure-min.css": ("pure-min.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def status(env, hardware):
    current = state.read(env)
    name, error, target = current["state"], current.get("error"), current.get("target")
    if name not in BUSY and env.pending.exists():
        # 已按更新，套用服務還沒寫狀態
        name, error, target = "verifying", None, bundle.version_of(env.pending)
    return {"state": name, "error": error, "version": env.version(), "slot": env.slot(),
            "target": target, "uploaded": bundle.version_of(env.upload),
            "progress": current.get("progress") if name == "writing" else None,
            "device": socket.gethostname(), **hardware}


def _busy(env):
    return env.pending.exists() or state.read(env)["state"] in BUSY


def _failure(code, error):
    return code, {"ok": False, "error": error}


def make_server(env, host, port, static_dir):
    lock = threading.Lock()  # 一次只處理一個上傳或更新
    env.part.unlink(missing_ok=True)
    hardware = hwinfo.read(env)  # 開機後不會變，啟動時讀一次

    class Handler(BaseHTTPRequestHandler):
        timeout = 60

        def reply(self, code, body, content_type="application/json"):
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/status":
                self.reply(200, status(env, hardware))
            elif self.path in STATIC:
                name, content_type = STATIC[self.path]
                self.reply(200, (Path(static_dir) / name).read_bytes(), content_type)
            else:
                self.send_error(404)

        def drain(self, length):
            """拒絕前先把本文讀掉，瀏覽器才收得到回應。"""
            while length > 0:
                chunk = self.rfile.read(min(length, CHUNK))
                if not chunk:
                    break
                length -= len(chunk)

        # 接收上傳（呼叫前 do_PUT 已拿到 lock）：
        #
        #   忙碌中？ ──是──> 409 busy
        #      │否
        #   刪舊 upload.ota ──> 空間夠？ ──否──> 507 no_space
        #      │是
        #   寫入 upload.part ─┬─ 提早斷線 ──> 400 bad_bundle
        #      │              └─ 磁碟滿 ───> 507 no_space
        #   讀得到版本號？ ──否──> 400 bad_bundle（雜湊留給 apply 檢查）
        #      │是
        #   改名 upload.ota ──> 202
        def receive(self, length):
            if _busy(env):
                self.drain(length)
                return _failure(409, "busy")
            env.upload.unlink(missing_ok=True)  # 舊檔先刪，騰出空間
            if shutil.disk_usage(env.incoming).free < length:
                self.drain(length)
                return _failure(507, "no_space")
            left = length
            try:
                with open(env.part, "wb") as file:
                    while left:
                        chunk = self.rfile.read(min(left, CHUNK))
                        if not chunk:
                            return _failure(400, "bad_bundle")
                        file.write(chunk)
                        left -= len(chunk)
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
                self.drain(left)
                return _failure(507, "no_space")
            version = bundle.version_of(env.part)
            if version is None:
                return _failure(400, "bad_bundle")
            env.part.replace(env.upload)
            return 202, {"ok": True, "version": version}

        def do_PUT(self):
            if self.path != "/api/upload":
                return self.send_error(404)
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if length <= 0:
                return self.reply(*_failure(411, "bad_bundle"))
            if not lock.acquire(blocking=False):
                self.drain(length)
                return self.reply(*_failure(409, "busy"))
            try:
                result = self.receive(length)
            finally:
                env.part.unlink(missing_ok=True)
                lock.release()
            self.reply(*result)

        # 網頁（非 root）只改檔名，寫分割區由 root 服務做：
        #
        #   忙碌中？ ──是──> 409 busy
        #      │否
        #   upload.ota ─改名─> pending.ota ──> 202
        #      │ 沒有檔案            │
        #      v                     v
        #   409 no_upload     apply.path 啟動 apply.py
        def apply_upload(self):
            if _busy(env):
                return _failure(409, "busy")
            try:
                env.upload.replace(env.pending)
            except FileNotFoundError:
                return _failure(409, "no_upload")
            return 202, {"ok": True}

        def do_POST(self):
            if self.path != "/api/apply":
                return self.send_error(404)
            if not lock.acquire(blocking=False):
                return self.reply(*_failure(409, "busy"))
            try:
                result = self.apply_upload()
            finally:
                lock.release()
            self.reply(*result)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="OTA update web server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    for name in ("ota_dir", "conf_dir", "slot_dir", "label_dir"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path,
                            default=getattr(Env, name))
    parser.add_argument("--static-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "web")
    args = parser.parse_args()
    env = Env(ota_dir=args.ota_dir, conf_dir=args.conf_dir,
              slot_dir=args.slot_dir, label_dir=args.label_dir)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server = make_server(env, args.host, args.port, args.static_dir)
    logging.info("http://%s:%d", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
