"""更新狀態檔 state.json。

idle ──> verifying ──> writing ──> pending ──> committed / rolled_back
              └────────────┴──> failed
"""
import json
import os


def atomic_write(path, text):
    """寫暫存檔、fsync、rename，讓斷電後只會看到舊的或新的內容。"""
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    try:
        os.chmod(temp, 0o644)
    except PermissionError:
        pass  # FAT（/bootfs）不支援改權限
    os.replace(temp, path)
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def read(env):
    try:
        data = json.loads((env.ota_dir / "state.json").read_text(encoding="utf-8"))
        data["state"]
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "idle", "error": None, "target": None}


def write(env, state, *, error=None, target=None, slot_dev=None, progress=None):
    data = {"state": state, "error": error, "target": target}
    if slot_dev:
        data["slot_dev"] = slot_dev
    if progress:
        data["progress"] = progress
    atomic_write(env.ota_dir / "state.json", json.dumps(data))
