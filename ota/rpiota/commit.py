"""開機後以 root 執行：判定上一次更新的結果。

verifying / writing ──> failed (interrupted)
pending ─┬─ 開在舊 slot ──────────────> rolled_back
         └─ 開在新 slot ─┬─ 健康 ────> 改寫 autoboot.txt ─> committed
                         ├─ 逾時 ────> 一般重開機（回舊 slot）
                         └─ 確認出錯 ─> 重開機（回舊 slot）
"""
import logging
import os
import sys
import time

from . import state
from .env import Env

log = logging.getLogger("rpiota-commit")


def _on_target(env, current):
    active = env.slot_dir / "active" / "system"
    return os.path.realpath(active) == current.get("slot_dev")


def _units(env):
    try:
        lines = env.conf("health.units").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines
            if line.strip() and not line.strip().startswith("#")]


def _healthy(env):
    units = _units(env)
    try:
        for unit in units:
            env.run(["systemctl", "is-active", "--quiet", unit])
    except Exception:
        return False
    return bool(units)


# 判定流程（整體狀態圖見本檔開頭）：
#
#   state 是 verifying / writing？ ──是──> 刪暫存檔，failed(interrupted)
#        │否
#   state 是 pending？ ──否──> 原狀態不動
#        │是
#   開在目標 slot？ ──否──> rolled_back
#        │是               （先前記了原因就沿用）
#        v
#   ┌─> 健康檢查：成功次數 +1，失敗歸零
#   │       ├─ 連續 2 次成功 ──> rpi-slot-tryboot 產生內容
#   │       │                    ──> 改寫 autoboot.txt ──> committed
#   │       ├─ 超過 timeout_s ──> 記 pending(health_failed) ──> reboot
#   │       │                    ──> 回舊 slot，下次開機判為 rolled_back
#   └───────┴─ 其他：等 interval_s 秒再查
def commit(env, timeout_s=180, interval_s=5, sleep=time.sleep, clock=time.monotonic):
    """回傳最後狀態。"""
    current = state.read(env)
    status, target = current["state"], current.get("target")
    if status in ("verifying", "writing"):
        env.pending.unlink(missing_ok=True)
        env.part.unlink(missing_ok=True)
        state.write(env, "failed", error="interrupted", target=target)
        return "failed"
    if status != "pending":
        return status
    if not _on_target(env, current):
        # pending 時記下的 error 就是退回的原因；沒記代表新版本沒開起來
        error = current.get("error") or "rolled_back"
        state.write(env, "rolled_back", error=error, target=target)
        return "rolled_back"
    deadline = clock() + timeout_s
    passed = 0
    while True:
        passed = passed + 1 if _healthy(env) else 0
        if passed >= 2:
            config = env.run(["rpi-slot-tryboot"])
            if not config.strip():
                raise ValueError("rpi-slot-tryboot 沒有輸出")
            state.atomic_write(env.autoboot, config)
            state.write(env, "committed", target=target)
            return "committed"
        if clock() >= deadline:
            break
        sleep(interval_s)
    state.write(env, "pending", error="health_failed", target=target,
                slot_dev=current.get("slot_dev"))
    env.run(["reboot"])
    return "pending"


def _record_failure(env, current):
    """記下退回舊版的原因，回到舊 slot 後網頁才不會顯示成開機失敗。"""
    if current.get("error"):
        return  # 已經有更明確的原因（health_failed）
    try:
        state.write(env, "pending", error="commit_failed", target=current.get("target"),
                    slot_dev=current.get("slot_dev"))
    except OSError:
        log.exception("無法記錄失敗原因")  # 記不下來也要照常重開


# 結束碼決定要不要重開（service 設了 FailureAction=reboot）：
#
#   commit()
#     ├─ 正常返回 ──> 結果是 pending？ ──是──> 1 ；否 ──> 0
#     └─ 丟例外 ───> 仍是 pending 且開在新 slot？ ──否──> 0
#                          │是
#                     記下 commit_failed ──> 1
def main(env, **options):
    """只有「開在新 slot 且確認不了」才回非零，讓 systemd 重開機。"""
    try:
        result = commit(env, **options)
    except Exception:
        log.exception("確認失敗")
        current = state.read(env)
        if current["state"] != "pending" or not _on_target(env, current):
            return 0
        _record_failure(env, current)
        return 1
    log.info("更新狀態：%s", result)
    return int(result == "pending")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main(Env()))
