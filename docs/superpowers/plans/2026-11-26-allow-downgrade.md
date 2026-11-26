# Allow Downgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 任何版本的更新包都能安裝，且被寫入的 slot 下次開機時重建 `/var`。

**Architecture:** `apply` 拿掉建置時間比對，寫分割區前刪除目標 slot 的 `/persistent/slots/system_<a|b>/var/.updated`。

**Tech Stack:** Python 標準函式庫、unittest。

**Spec:** [2026-11-26-allow-downgrade-design.md](../specs/2026-11-26-allow-downgrade-design.md)

## Global Constraints

- 只用 Python 標準函式庫；測試要能在 Linux 與 Windows 跑（不用 symlink）。
- 更新包格式不變。
- 建置進行中：`ota/` 的修改先在副本完成並測試，再一次放回。
- 不 commit（工作區有使用者尚未提交的修改）。

## Review Focus

- 斷電：刪掉的 `.updated` 要 fsync 目錄，避免重開後復原。
- slot 判斷不出來時不得猜測，不寫任何分割區。

---

### Task 1: apply 允許舊版並重設目標 slot 的 /var

**Files:**
- Modify: `ota/rpiota/env.py`、`ota/rpiota/apply.py`、`ota/web/app.js`
- Test: `ota/tests/helpers.py`、`ota/tests/test_apply.py`、`ota/tests/test_web.py`

**Interfaces:**
- Produces: `Env.persistent_slots: Path = Path("/persistent/slots")`；`Env.slot(which: str = "active") -> str`（`a`、`b`、`?`，用 `os.path.samefile` 比對 label）。

- [ ] **Step 1: 寫失敗的測試**
  - `make_env`：hard link `system_a`→`active/system`、`system_b`→`other/system`；建立 `slots/system_{a,b}/var/.updated`。
  - `test_older_and_same_version_install`：epoch 500、1000 都得到 `pending`。
  - `test_resets_target_var`：成功後 b 的 `.updated` 不存在、a 的存在。
  - `test_missing_stamp_is_ok`：b 沒有 `.updated` 仍 `pending`。
  - `test_var_reset_failure_writes_nothing`：沒有 label／沒有 var 目錄／`.updated` 是目錄 → `failed(write_failed)`，分割區內容不變。
  - `test_rejected_keeps_stamp`：併入 `test_rejects`；移除 `not_newer` 案例。
  - `test_web`：狀態的 `slot` 改為 `a`。
- [ ] **Step 2:** `python3 -m unittest discover -s ota/tests -t ota`，預期新測試 FAIL。
- [ ] **Step 3: 實作** `env.slot(which)`；`apply._reset_var(env) -> None`（失敗丟例外，刪除後 fsync 目錄），在 `_targets` 之後、`state=writing` 之前呼叫；刪掉 epoch 比對與 `app.js` 的 `not_newer`；更新流程註解。
- [ ] **Step 4:** 同一指令，預期 `OK`。

### Task 2: 文件

**Files:** `docs/architecture.md`、`docs/build-update-bundle.md`、`image/README.md`、兩份 spec。

- [ ] **Step 1:** 移除「只接受較新」與 `not_newer`；實機檢查第 5 步改為退版並看 `journalctl -b -u slot-var-reset`；新 spec 狀態改為已核可。
- [ ] **Step 2:** `grep -rn 'not_newer' docs image ota README.md`，預期只剩新 spec 與本計畫。
