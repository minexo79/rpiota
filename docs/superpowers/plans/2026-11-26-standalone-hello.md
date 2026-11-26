# 獨立範例應用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `hello.py` 成為不依賴 `rpiota` 的範例應用，裝到 `/opt/app/hello.py`。

**Architecture:** `app/hello.py` 自己讀版本檔；`install.sh` 把它裝到 `<rootfs>/opt/app/`，service 指向新路徑。OTA 程式不改。

**Tech Stack:** Python 3.13 標準函式庫、bash、systemd。

**Spec:** `docs/superpowers/specs/2026-11-26-standalone-hello-design.md`

## Global Constraints

- 原始碼在 `app/hello.py`，裝置路徑是 `/opt/app/hello.py`。
- `hello.py` 只用標準函式庫，不 import `rpiota`。
- 版本檔 `/etc/rpiota/version`；讀不到或空白時印 `unknown`。
- 每 3 秒印 `Hello OTA <版本>`，立即 flush。
- 服務名稱 `rpiota-hello`、開機啟動、`health.units` 內容都不變。
- 此資料夾不是 git repo，沒有 commit 步驟。

## Review Focus

- 版本檔不存在：印 `Hello OTA unknown`，不結束程式（Task 1 測試）。
- 版本檔是空白：印 `Hello OTA unknown`（Task 1 測試）。
- 只複製 `hello.py` 到別處、沒有 `rpiota`：能載入（Task 1 測試）。
- `ota/` 旁的 `app/` 路徑寫錯：安裝腳本要把檔案放到 `opt/app/`（Task 2 試跑）。
- 舊路徑 `usr/lib/rpiota/app` 或 `sample/` 殘留在文件或腳本：搜尋結果應為零（Task 2 搜尋）。

---

### Task 1: 獨立的 hello.py

**Files:**
- Modify: `app/hello.py`
- Test: `ota/tests/test_hello.py`

**Interfaces:**
- Produces: `VERSION_FILE = Path("/etc/rpiota/version")`、`version(path: Path) -> str`、`run(path=VERSION_FILE, count=None, sleep=time.sleep, out=_print) -> None`

- [ ] **Step 1: 改寫測試**

`ota/tests/test_hello.py` 不再使用 `make_env`，`sys.path` 改指向 `parents[2] / "app"`。`setUp` 建暫存目錄，`self.path = Path(tmp) / "version"`。

```python
    def run_hello(self, count=1):
        lines, sleeps = [], []
        hello.run(self.path, count=count, sleep=sleeps.append, out=lines.append)
        return lines, sleeps

    def test_hello_prints_version_every_three_seconds(self):
        self.path.write_text("1.0\n", encoding="utf-8")
        self.assertEqual(self.run_hello(2), (["Hello OTA 1.0"] * 2, [3, 3]))

    def test_missing_version_file_prints_unknown(self):
        self.assertEqual(self.run_hello()[0], ["Hello OTA unknown"])

    def test_blank_version_file_prints_unknown(self):
        self.path.write_text("\n", encoding="utf-8")
        self.assertEqual(self.run_hello()[0], ["Hello OTA unknown"])

    def test_default_version_file(self):
        self.assertEqual(hello.VERSION_FILE, Path("/etc/rpiota/version"))

    def test_loads_without_rpiota(self):
        copy = Path(self.tmp.name) / "hello.py"
        shutil.copy(hello.__file__, copy)
        subprocess.run(
            [sys.executable, "-I", "-c",
             "import runpy, sys; runpy.run_path(sys.argv[1])", str(copy)],
            check=True, cwd=self.tmp.name)
```

- [ ] **Step 2: 確認測試失敗**

Run: `python -m unittest discover -s ota/tests -t ota -p test_hello.py`
Expected: FAIL（找不到 `rpiota` 或沒有 `VERSION_FILE`）

- [ ] **Step 3: 改寫 `app/hello.py`**

照 Interfaces 實作。`version` 以 UTF-8 讀檔並 `strip()`，`OSError` 或空字串回 `"unknown"`；`run` 每次迴圈重讀。檔頭說明的流程圖保留。

- [ ] **Step 4: 確認測試通過**

Run: 同 Step 2。Expected: 5 個測試，`OK`

### Task 2: 安裝路徑、服務與文件

**Files:**
- Modify: `image/install.sh`、`image/systemd/rpiota-hello.service`
- Modify: `README.md`、`docs/architecture.md`、`image/README.md`、`docs/superpowers/specs/2026-11-26-simple-ota-design.md`

**Interfaces:**
- Consumes: `app/hello.py`（Task 1）

- [ ] **Step 1: `install.sh`**

建立目錄清單以 `"$rootfs/opt/app"` 取代 `"$lib/app"`；來源改為 `"$src"/../app/*.py`，目的地 `"$rootfs/opt/app/"`，權限 0644。開頭註解分成 `ota/rpiota, ota/web ─> /usr/lib/rpiota/` 與 `app ─> /opt/app/`。

- [ ] **Step 2: `rpiota-hello.service`**

刪除 `Environment=PYTHONPATH=/usr/lib/rpiota`；`ExecStart=/usr/bin/python3 /opt/app/hello.py`。

- [ ] **Step 3: 文件**

- `README.md` 檔案樹：`app/` 已正確，不改。
- `docs/architecture.md` 元件表：`app/hello.py` 註明裝在 `/opt/app/`。
- `image/README.md`「裝置上的內容」：加一列 `/opt/app/`，內容為「範例應用 `hello.py`」。
- `2026-11-26-simple-ota-design.md`：檔案樹不改；「映像端內容」註明範例裝到 `/opt/app/`。

- [ ] **Step 4: 試跑 `install.sh`**

用暫存目錄當 rootfs（先建 `usr/lib/os-release` 空檔），PATH 前面放一個直接 `exit 0` 的假 `chroot`；設定 `IGconf_rpiota_src=<專案>/ota`、`IGconf_rpiota_version=1.0`、`IGconf_rpiota_epoch=1`，執行 `bash image/install.sh <rootfs>`。暫存目錄放在專案外。

Expected: 結束碼 0；`<rootfs>/opt/app/hello.py` 存在；`<rootfs>/usr/lib/rpiota/app` 不存在。

- [ ] **Step 5: 搜尋舊路徑**

在 `README.md`、`docs/`（不含 `docs/superpowers/` 的本次設計與計畫）、`image/`、`ota/` 搜尋 `rpiota/app|$lib/app|sample/`。
Expected: 沒有結果（舊版計畫檔是歷史紀錄，不改）。

- [ ] **Step 6: 跑全部測試**

Run: `python -m unittest discover -s ota/tests -t ota`
Expected: 最後一行 `OK`
