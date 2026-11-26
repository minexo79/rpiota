# 允許安裝舊版更新包

狀態：已核可（2026-11-26），實機驗證 OK（2026-11-27）。

## 目的

裝置可以安裝任何版本的更新包，需要時能退回舊版。目前 `apply` 只接受建置時間比執行中映像新的包（`not_newer`）。

## 範圍

- 舊版、同版、新版一律可安裝。
- 流程不變：寫入閒置 slot、試開機、健康檢查通過才保留，否則回到原本版本。
- 不做：網頁上的「切回上一版」按鈕、降版確認視窗。
- 更新包格式不變。`source_date_epoch` 與 `/etc/rpiota/epoch` 照舊寫入，只是 `apply` 不再比較。

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| A：只拿掉檢查 | 改動最少；舊版可能沿用較新版本留下的 `/var` | 未採用 |
| B：拿掉檢查，寫入的 slot 一律重設 `/var` | 多幾行程式，依賴 rpi-image-gen 內部機制 | **採用**（2026-11-26 你選定） |

## 設計

**檢查**：刪掉建置時間比對與 `not_newer` 錯誤代碼（`apply.py`、`app.js`）。機型、雜湊、容量檢查保留。

**重設 `/var`**：rpi-image-gen 只在 `/usr` 比 slot 的 `/var/.updated` 新時重設 `/var`；這個檔案不存在時也會重設。因此 `apply`：

1. 判斷閒置 slot 是 `a` 或 `b`：比對 `by-slot/other/system` 與 `by-partlabel/system_a`、`system_b`。
2. 全部檢查通過後、寫分割區之前，刪除 `/persistent/slots/system_<a|b>/var/.updated`。
3. 下次開進該 slot 時，系統用映像內容重建它的 `/var`。

| 情況 | 行為 |
|---|---|
| `.updated` 本來就不存在 | 視為成功 |
| 判斷不出 slot、`var` 目錄不存在、或刪除失敗 | `failed(write_failed)`，不寫分割區 |
| 更新包被拒絕（機型、雜湊、容量） | 不動 `.updated` |

只影響被覆寫的 slot。執行中 slot 的 `/var`、`/home`、journal、跨 slot 共用資料都保留。

**限制**：跨 slot 共用資料與 `ConditionNeedsUpdate=/etc` 的行為由 rpi-image-gen 決定，退版時舊系統讀到的是目前的共用資料。本專案目前沒有宣告自己的共用路徑。

## 測試與驗證

單元測試：舊版與同版可安裝；成功寫入時刪掉目標 slot 的 `.updated`、另一個 slot 的保留；上表三種情況；移除 `not_newer` 案例。

文件同步更新：`docs/build-update-bundle.md`、`image/README.md`（含實機檢查第 5 步）、`docs/superpowers/specs/2026-11-26-simple-ota-design.md`。

**實機驗證 OK（2026-11-27）**：`/var` 重設是讀 rpi-image-gen 原始碼推得的；確認方式是退版開機後 `journalctl -b -u slot-var-reset` 顯示有執行。

**注意**：這項功能在裝置端，已燒錄的裝置要先更新到含此修改的版本，之後才能退版。退到不含此修改的舊版後，該版本仍只接受較新的包。

## 實作時自行決定

模組內的函式切分與測試寫法；`/persistent/slots` 的路徑做成 `Env` 可替換的欄位。
