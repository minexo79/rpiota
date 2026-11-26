"""更新狀態檔 state.json 與斷電安全的寫檔函式。

修改紀錄：
  2026-11-26：新增 overwrite，原地覆寫 FAT 上的 autoboot.txt，避免斷電後檔案損壞。

idle ──> verifying ──> writing ──> pending ──> committed / rolled_back
              └────────────┴──> failed
"""
import json
import os


def atomic_write(path, text):
    """寫暫存檔、fsync、rename，讓斷電後只會看到舊的或新的內容（ext4；FAT 不適用）。"""
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    try:
        os.chmod(temp, 0o644)
    except PermissionError:
        pass  # 檔案系統不支援改權限
    os.replace(temp, path)
    fsync_dir(path.parent)


# autoboot.txt 在 FAT 分割區。不能用 atomic_write：
#
#   寫新檔 ──> 改名蓋掉舊檔 ──> fsync 目錄 ──> 斷電
#     新的目錄項目可能還沒寫到卡上，舊項目卻指向已釋放的叢集，
#     之後檔案系統修復可能把檔案清成空的，裝置就開不了機。
#
# overwrite 直接改原本的檔案：
#
#   檔案存在？ ──否──> 建立新檔（wb）
#        │是
#   開啟但不清空（r+b）
#        v
#   從開頭寫入新內容 ──> 截掉後面多出的舊內容 ──> flush、fsync
#        │
#   剛才是新建的？ ──是──> 再 fsync 目錄
def overwrite(path, text):
    """原地覆寫小於一個磁區（512 bytes）的檔案，給 autoboot.txt 用。

    不換叢集、不改名。寫入磁區的瞬間斷電能否保住資料，仍取決於 SD 卡。
    """
    created = not path.exists()
    # r+b：開啟時保留舊內容，中途斷電不會先變成空檔
    with open(path, "wb" if created else "r+b") as file:
        # 用 bytes 寫入，換行字元不做轉換
        file.write(text.encode("utf-8"))
        # 一定要先寫再截斷；順序反過來會有一段時間是空檔
        file.truncate()
        file.flush()              # Python 緩衝區 ─> 核心
        os.fsync(file.fileno())   # 核心 ─> SD 卡
    if created:
        fsync_dir(path.parent)    # 新檔案的目錄項目也要寫到卡上


def fsync_dir(path):
    """讓目錄內的改名、刪除在斷電後仍然有效（只有 POSIX 需要）。"""
    if os.name == "posix":
        directory = os.open(path, os.O_RDONLY)
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
