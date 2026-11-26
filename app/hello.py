"""每 3 秒印出版本號，用來確認更新有沒有生效。

獨立範例應用，只用標準函式庫，可以整支複製去改。

/etc/rpiota/version ──> stdout ──> journald
"""
import time
from pathlib import Path

VERSION_FILE = Path("/etc/rpiota/version")


def version(path):
    try:
        return path.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _print(line):
    print(line, flush=True)


def run(path=VERSION_FILE, count=None, sleep=time.sleep, out=_print):
    done = 0
    while count is None or done < count:
        out(f"Hello OTA {version(path)}")
        sleep(3)
        done += 1


if __name__ == "__main__":
    run()
