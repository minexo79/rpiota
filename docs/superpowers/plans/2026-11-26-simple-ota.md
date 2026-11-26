# 精簡版 A/B OTA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans（本次在同一個 session 內直接實作）。

**Goal:** 完成 OTA 的 Python 程式、更新網頁與打包指令；映像建置由使用者處理。

**Architecture:** 非 root 網頁服務收檔，按「更新」後改名觸發 root 套用服務寫閒置 slot，開機後由確認服務決定保留或回滾。

**Tech Stack:** Python 3.13 標準函式庫、`zstd`、Pure.css 3.0.0。

**Spec:** [設計文件](../specs/2026-11-26-simple-ota-design.md)

## Global Constraints

- 只用標準函式庫；中文註解、英文識別字。
- 狀態：`idle`、`verifying`、`writing`、`pending`、`committed`、`failed`、`rolled_back`。
- 錯誤代碼：`bad_bundle`、`bad_hash`、`wrong_device`、`not_newer`、`too_large`、`busy`、`write_failed`、`interrupted`、`health_failed`、`rolled_back`、`no_space`、`no_upload`。
- 測試：`python -m unittest discover -s ota/tests -t ota`（PATH 需含 `zstd`）。
- 專案不是 git repo，不做 commit。

## 相對設計的調整

sparse 映像改由 Python 解析並寫入（`sparse.py`），不用 `simg2img` 與 `tar`：`simg2img` 預期輸入可 seek，接管線很可能失敗，改成先解壓到暫存檔則要多佔數 GB。

## Review Focus

- 寫入中斷電 → 舊 slot 開機後 `failed`/`interrupted`，殘留檔刪除（Task 2）。
- 閒置與目前 slot 指到同一裝置，或裝置節點不存在 → `write_failed`，不寫也不建檔（Task 2）。
- `pending` 時上傳或按更新 → `busy`（Task 2、3）。
- 上傳到一半斷線 → `upload.part`、`upload.ota` 都不存在（Task 3）。
- 截斷或超出分割區的 sparse 資料 → `write_failed`（Task 1、2）。

## Tasks

### Task 1: 基礎、更新包、Hello

**Files:** `ota/rpiota/{__init__,env,state,sparse,bundle}.py`、`app/hello.py`、`ota/tests/{helpers,test_bundle,test_sparse}.py`

**Interfaces — Produces:**
- `env.Env(ota_dir, conf_dir, slot_dir, label_dir, os_release, autoboot, run, part_size)`；屬性 `incoming, pending, upload, part`；方法 `version() -> str`、`slot() -> "a"|"b"|"?"`
- `state.read(env) -> dict`、`state.write(env, state, error=None, target=None, slot_dev=None)`、`state.atomic_write(path, text)`（state.json）、`state.overwrite(path, text)`（FAT 上的 autoboot.txt）
- `sparse.raw_size(path) -> int`、`sparse.write(stream, out, limit) -> int`（資料不合法丟 `ValueError`）
- `bundle.BundleError(code)`、`Manifest`、`pack(boot, system, out, *, version, epoch, device_class="cm4")`、`read_manifest(path)`、`verify(path)`
- `hello.run(env, count=None, sleep=time.sleep)`

- [ ] 寫測試：pack→verify 欄位一致；改映像 → `bad_hash`；多餘或穿越路徑項目、非 tar、manifest > 64 KiB、欄位型別錯 → `bad_bundle`；sparse 的 raw/fill/don't care 寫出正確位元組；截斷、超過 limit → `ValueError`；hello 印 `Hello OTA <版本>`
- [ ] 確認失敗 → 實作 → 全過

### Task 2: 套用與確認

**Files:** `ota/rpiota/{apply,commit}.py`、`ota/tests/{test_apply,test_commit}.py`

**Interfaces — Produces:** `apply.apply(env) -> None`、`commit.commit(env, timeout_s=180, interval_s=5, sleep=..., clock=...) -> str`、`commit.main(env) -> int`

- [ ] 寫測試：套用與確認各分支的案例，加上 Review Focus 第 1、2、5 項
- [ ] 確認失敗 → 實作 → 全過

### Task 3: 網頁

**Files:** `ota/rpiota/web.py`、`ota/web/{index.html,pure-min.css}`、`ota/tests/test_web.py`

**Interfaces — Produces:** `web.make_server(env, host, port, static_dir) -> ThreadingHTTPServer`

- [ ] 寫測試：設計文件「元件 / web」表格各列；斷線不留檔；路徑穿越 404
- [ ] 確認失敗 → 實作 → 全過
- [ ] 下載 `pure-min.css`（已核可），寫 `index.html`，瀏覽器實際上傳並按更新

### Task 4: 映像端說明

**Files:** `ota/README.md`

- [ ] 套件、安裝路徑、設定檔、目錄權限、四個 unit 的必要設定、打包指令、實機檢查清單
- [ ] 全部測試再跑一次，自我審查
