"""以 root 執行：檢查 pending.ota、寫入閒置 slot、試開機。

pending.ota ─> 檢查（雜湊、機型、版本、容量）─> 寫 boot、system ─> state=pending
            ─> 刪掉 pending.ota ─> reboot "0 tryboot"
"""
import logging
import os
import subprocess
import tarfile
import threading

from . import bundle, sparse, state
from .env import Env

log = logging.getLogger("rpiota-apply")


# 對 boot、system 依序檢查：
#
#   by-slot/other/<part> ── 和 active 是同一個裝置？ ──是──> ValueError
#          │否
#   映像展開大小 > 分割區？ ──是──> UpdateError(too_large)
#          │否
#   列入寫入目標
def _targets(env, manifest):
    """回傳閒置 slot 的裝置，並確認它不是目前在用的那個、容量足夠。"""
    targets = {}
    for part in bundle.PARTS:
        other = env.slot_dir / "other" / part
        active = env.slot_dir / "active" / part
        if os.path.samefile(other, active):
            raise ValueError(f"{other} 指向目前使用中的分割區")
        if manifest.image(part).raw_size > env.part_size(other):
            raise bundle.UpdateError("too_large")
        targets[part] = other
    return targets


def _feed(source, sink, errors):
    try:
        with sink:
            while chunk := source.read(1 << 20):
                sink.write(chunk)
    except Exception as error:  # zstd 提早結束時會是 BrokenPipeError
        errors.append(error)


def _reporter(env, version, part):
    """百分比前進至少 2 才寫狀態檔，避免一直 fsync。"""
    last = None

    def report(done, total):
        nonlocal last
        percent = done * 100 // total
        if last is None or percent >= last + 2 or (percent == 100 and last != 100):
            last = percent
            state.write(env, "writing", target=version,
                        progress={"part": part, "percent": percent})

    report(0, 1)
    return report


# 邊解壓邊寫，不落地暫存檔：
#
#   .ota 內的 *.sparse.zst
#          │  feeder 執行緒（_feed）
#          v
#      zstd -dc
#          │  主執行緒
#          v
#     sparse.write ──> 閒置分割區
#
#   寫完後：還有多餘資料？ → zstd 非零結束或 feeder 出錯？ → fsync
#   任一步失敗都丟例外；sparse.write 中途失敗時先 kill zstd
def _write_image(env, member, device, progress):
    """tar 項目 ─> zstd -dc ─> sparse.write ─> 分割區。"""
    limit = env.part_size(device)
    # r+b：裝置節點不存在時直接失敗，不會建出一般檔案
    with open(device, "r+b") as out:
        process = subprocess.Popen(
            ["zstd", "-q", "-dc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        errors = []
        feeder = threading.Thread(target=_feed, args=(member, process.stdin, errors))
        feeder.start()
        try:
            sparse.write(process.stdout, out, limit, progress)
            if process.stdout.read(1):
                raise ValueError("sparse 映像後面有多餘資料")
        except BaseException:
            process.kill()
            raise
        finally:
            feeder.join()
            process.stdout.close()
            code = process.wait()
        if code or errors:
            raise ValueError(f"解壓縮失敗（{code}）{errors}")
        out.flush()
        os.fsync(out.fileno())


# 全部檢查通過後才開始寫分割區：
#
#   state=verifying
#     ├─ 項目名稱、順序、雜湊 ──不符──> UpdateError(bad_bundle / bad_hash)
#     ├─ 機型 ──────────────────不符──> UpdateError(wrong_device)
#     ├─ epoch 比目前新？ ──────否────> UpdateError(not_newer)
#     └─ 閒置 slot 與容量（_targets）
#   state=writing ──> 寫 boot ──> 寫 system
def _install(env):
    """回傳 (版本, 目標 system 裝置)。"""
    state.write(env, "verifying")
    manifest = bundle.verify(env.pending)
    version = manifest.version
    if manifest.device_class != env.conf("device-class"):
        raise bundle.UpdateError("wrong_device")
    if manifest.source_date_epoch <= int(env.conf("epoch")):
        raise bundle.UpdateError("not_newer")
    targets = _targets(env, manifest)
    state.write(env, "writing", target=version)
    with tarfile.open(env.pending, "r:") as tar:
        for part, device in targets.items():
            member = tar.extractfile(manifest.image(part).file)
            _write_image(env, member, device, _reporter(env, version, part))
    return version, os.path.realpath(targets["system"])


# 套用更新的主流程（rpiota-apply.path 看到 pending.ota 時啟動）：
#
#   pending.ota 存在？ ──否──> 結束
#        │是
#   state 是 pending？ ──是──> 刪 pending.ota，結束（狀態不改）
#        │否
#   _install（檢查 + 寫入閒置 slot）
#        ├─ 被拒絕 ──> state=failed（拒絕原因）──┐
#        ├─ 其他例外 ─> state=failed(write_failed)┤
#        └─ 成功 ────> state=pending             │
#                          │                     │
#   刪 pending.ota <───────┴─────────────────────┘  （成功、失敗都刪）
#        │ 只有成功才往下
#   reboot "0 tryboot" ──失敗──> state=failed(write_failed)
#        │
#   開機後交給 commit.py
def apply(env):
    if not env.pending.exists():
        return
    if state.read(env)["state"] == "pending":
        # 閒置 slot 是唯一確認過的舊版本，這時覆寫就沒有退路
        log.error("busy：上一次更新還沒確認")
        env.pending.unlink()
        return
    target = None
    try:
        target = bundle.version_of(env.pending)
        version, slot_dev = _install(env)
        state.write(env, "pending", target=version, slot_dev=slot_dev)
    except bundle.UpdateError as error:
        log.error("拒絕更新：%s", error.code)
        state.write(env, "failed", error=error.code, target=target)
        return
    except Exception:
        log.exception("寫入失敗")
        state.write(env, "failed", error="write_failed", target=target)
        return
    finally:
        # 一定要刪，否則 path unit 會無限重跑
        env.pending.unlink(missing_ok=True)
    try:
        env.run(["reboot", "0 tryboot"])
    except Exception:
        log.exception("無法重開機")
        state.write(env, "failed", error="write_failed", target=version)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    apply(Env())
