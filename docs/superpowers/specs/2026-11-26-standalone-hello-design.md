# hello.py 改為獨立範例應用

狀態：已核可（2026-11-26）。實作中依你的指示把原始碼目錄 `sample/` 改名為 `app/`。

## 目的

`hello.py` 當作獨立範例應用：和 OTA 本體分開放，可以整支複製去改成自己的應用。

## 目標與不做

- 目標：裝到 `/opt/app/hello.py`，不 import `rpiota`。
- 不做：改服務名稱、改輸出內容、改 OTA 流程、讓範例在更新後保留舊檔。

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| 完全獨立 | 可單獨複製；版本檔路徑在兩處各寫一次 | **採用**（2026-11-26 你選定） |
| 只搬路徑 | 改動最少；仍依賴 OTA 程式 | 未採用 |

## 改動

| 檔案 | 內容 |
|---|---|
| `app/hello.py` | 只用標準函式庫，自己讀 `/etc/rpiota/version` |
| `image/install.sh` | `app/*.py` 裝到 `<rootfs>/opt/app/`，不再建立 `/usr/lib/rpiota/app/`；更新開頭註解 |
| `image/systemd/rpiota-hello.service` | `ExecStart` 改為 `/opt/app/hello.py`，移除 `PYTHONPATH` |
| `ota/tests/test_hello.py` | 從 `app/` 匯入，用暫存版本檔測試 |
| `docs/architecture.md`、`image/README.md`、`2026-11-26-simple-ota-design.md` | 更新路徑 |

## 行為

- 每 3 秒印 `Hello OTA <版本>`，立即 flush。
- 版本檔讀不到時的處理沿用現在 `Env.version()` 的行為。
- 服務仍叫 `rpiota-hello`，開機啟動，仍列在 `health.units`，啟動失敗會讓更新回滾。
- `/opt/app/` 在系統分割區，OTA 更新時跟著換成新版（依分割區設計推斷，實機未驗證）。

## 驗證

跑全部單元測試。映像建置、systemd 與實機不驗證。
