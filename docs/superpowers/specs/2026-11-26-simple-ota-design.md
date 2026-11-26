# 精簡版 A/B OTA 設計

狀態：已核可（2026-11-26），程式已實作，實機未驗證。

## 目的

用最少的零件跑通「瀏覽器上傳 → 寫入閒置 slot → 試開機 → 健康才切換」。用 Hello OTA 程式印出的版本號確認更新有沒有生效。

不做：簽章與金鑰、上傳 token、中英訊息表、差分更新、把其他應用裝進映像。

**限制**：沒有簽章也沒有 token，同網段任何人都能把任意系統映像裝到裝置上。只適合實驗網路。

## 分工

| 誰 | 做什麼 |
|---|---|
| 代理 | Python 程式、網頁、打包指令、單元測試、映像腳本（config、layer、systemd units、`build.sh`） |
| 你 | 驗證：執行建置、燒錄、實機檢查 |

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| 精簡 A/B | 保留回滾；沒有來源驗證 | **採用**（2026-11-26 你選定） |
| 完整版（含簽章、token） | 較安全；程式與設定多不少 | 未採用 |
| 只換 Python 檔 | 最簡單；不產生 OTA 映像 | 未採用：不符需求 |

## 檔案

```
ota/
  rpiota/  env.py state.py sparse.py bundle.py apply.py commit.py web.py
  web/           index.html app.js pure-min.css
  tests/
app/             hello.py
image/           build.sh install.sh config/ layer/ systemd/ README.md
```

只用 Python 標準函式庫。Pi 上的外部指令：`zstd`、`rpi-slot-tryboot`、`systemctl`、`reboot`。

實作時的調整：sparse 映像由 `sparse.py` 邊讀邊寫，取代 `simg2img` 與 `tar`（`simg2img` 預期輸入可 seek，接管線很可能失敗）。上傳內容不是更新包時回 400 `bad_bundle`。

## 元件

**hello**：每 3 秒印一行 `Hello OTA <版本>` 到 stdout（立即 flush），由 journald 收。版本讀 `/etc/rpiota/version`。

**bundle**：`python3 -m rpiota.bundle --image-dir D --version V --epoch N --out F`。輸出未壓縮 tar，依序為 `manifest.json`、`boot.sparse.zst`、`system.sparse.zst`。manifest：`format`=1、`device_class`=`cm4`、`version`、`source_date_epoch`，以及兩個映像的 `sha256`（`.zst` 檔）與 `raw_size`。

**web**（非 root，`0.0.0.0:8080`）

| 路徑 | 行為 |
|---|---|
| `GET /` | 亮色 Pure.css 英文單頁（`index.html` + `app.js`），由上而下三個有外框的區塊：`Information`（版本、裝置名稱，用 `pure-table`）、`Upgrade`（進度條、`Choose File`／檔名／`Update`，上傳後直接套用）、`Log`（訊息窗可收合，預設收合）；外框是自訂 CSS，按鈕用 Raspberry Pi 紅 `#C51A4A` |
| `GET /api/status` | `state`、`error`、`version`、`device`（主機名稱）、`slot`、`target`、`uploaded`（已上傳檔案的版本或 null）、`progress`（寫入中為 `{part, percent}`） |
| `PUT /api/upload` | 原始檔案內容 → `incoming/upload.part`，收滿才改名 `upload.ota` |
| `POST /api/apply` | `upload.ota` 改名為 `pending.ota`，觸發套用 |

忙碌（`verifying`／`writing`／`pending`，或 `pending.ota` 已存在）時上傳與更新都回 409。`apply` 沒有已上傳檔案回 409。空間不足回 507。

**apply**（root）：檢查格式、雜湊、機型、`source_date_epoch` 較新、容量；寫入閒置 slot；`state=pending`；`reboot "0 tryboot"`。結束時一定刪掉 `pending.ota`。

**commit**（root）：`health.units` 內服務連續兩次 active 才改寫 `autoboot.txt`；180 秒逾時就重開回舊版。

狀態值：`idle`、`verifying`、`writing`、`pending`、`committed`、`failed`、`rolled_back`。錯誤代碼：`bad_bundle`、`bad_hash`、`wrong_device`、`not_newer`、`too_large`、`busy`、`write_failed`、`interrupted`、`health_failed`、`commit_failed`、`rolled_back`、`no_space`、`no_upload`。網頁把代碼直接寫成英文說明。

## 映像端內容

- 套件 `python3 zstd`；程式裝到 `/usr/lib/rpiota/`，範例應用 `app/hello.py` 裝到 `/opt/app/`。
- `/etc/rpiota/`：`version`、`device-class`、`health.units`。
- `/persistent/ota` 0755 root；`incoming` 0770 root:`rpiota`。
- units：hello、web（`User=rpiota`）、apply（`.path` 監看 `incoming/pending.ota`）、commit（oneshot、`FailureAction=reboot`）。
- 分割區沿用 `image-rota`；rpi-image-gen 的 commit 鎖定在 `image/build.sh`。

詳細指令與路徑寫在 `image/README.md`。

時間戳改存 `/etc/rpiota/epoch`，`apply` 讀它而不是 `os-release`：查 rpi-image-gen 原始碼找不到寫入 `IG_SOURCE_DATE_EPOCH` 的程式，且外部的 `SOURCE_DATE_EPOCH` 不會傳進建置。

## 驗證

本機（Windows、Python 3.13）跑單元測試，分割區用一般檔案、重開機用假函式代替，網頁用瀏覽器實際操作。**不驗證**：真實的 sparse 寫入、systemd、tryboot、實機開機。

## 需要下載

`pure-min.css` 3.0.0（BSD 授權，約 17 KB），來源 `https://cdn.jsdelivr.net/npm/purecss@3.0.0/build/pure-min.css`，放進 `ota/web/`，裝置離線也能用。
