# 映像建置

用 [rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen)（鎖定 commit `85a9345960c6e96a8b9269988ed5629b6f9e87d0`）建出 CM4 Lite（SD 卡）的 A/B 映像與更新包。整體架構見 [架構](../docs/architecture.md)。

## 需要的環境

rpi-image-gen 官方支援 **arm64 的 Debian Bookworm／Trixie 或 Raspberry Pi OS**。x86 靠 QEMU 可能可以，官方不保證。以一般使用者執行（不要用 root）。

另外需要 `git`、`python3`、`zstd`。專案請放在 Linux 檔案系統內、路徑不含空白（WSL 不要直接在 `/mnt/...` 底下建置）。從 Windows 複製過去時保持 LF 換行。

## 建置

```bash
bash image/build.sh --deps
```

```bash
bash image/build.sh --check
```

```bash
RPIOTA_VERSION=1.0.0 RPIOTA_SSH_PUBKEY=~/.ssh/id_ed25519.pub bash image/build.sh
```

`--deps` 只需做一次（會用 `sudo`）。第一次執行會把 rpi-image-gen 抓到 `<專案>/build/rpi-image-gen-ota`。

| 變數 | 說明 | 預設 |
|---|---|---|
| `RPIOTA_VERSION` | 版本號，英數字與 `. _ + -`，最長 64 字 | 必填 |
| `RPIOTA_SSH_PUBKEY` | 使用者 `pi` 的 SSH 公鑰檔 | 兩者至少一個 |
| `RPIOTA_PASSWORD` | `pi` 的密碼：8 字以上，含大小寫、數字、`@$!%*?&` 各一 | 兩者至少一個 |
| `RPIOTA_IG_DIR` | rpi-image-gen 目錄 | `<專案>/build/rpi-image-gen-ota` |
| `RPIOTA_WORK` | 建置目錄 | `<專案>/build/rpi-ota-work` |
| `RPIOTA_OUT` | 燒錄映像與更新包輸出目錄 | `<專案>/build` |

`RPIOTA_PASSWORD` 會經由命令列傳給建置工具，可能留在建置紀錄或輸出的設定檔裡，不要用其他地方在用的密碼。序列主控台登入需要密碼。

完成時印出兩個路徑：

- `build/rpiota-<版本>.img.zst`：第一次燒到 SD 卡（8 GB 以上），Raspberry Pi Imager 可直接使用。
- `build/update-<版本>.ota`：之後用網頁更新。

## 檔案

| 檔案 | 內容 |
|---|---|
| `build.sh` | 抓工具、建置、打包 |
| `config/ota.yaml` | 機型、分割區大小、使用者、layer |
| `layer/rpiota.yaml` | 加裝 `python3`、`zstd`、`avahi-daemon`，呼叫 `install.sh` |
| `install.sh` | 把程式、設定、units 放進 rootfs，建立 `rpiota` 使用者 |
| `systemd/` | 服務、tmpfiles、watchdog、健康檢查清單 |

`config/ota.yaml` 的 `trait: hw:ethernet` 依載板調整。映像沒有設定 Wi-Fi，請接網路線。主機名稱是 `rpiota`。

## 裝置上的內容

| 路徑 | 內容 |
|---|---|
| `/usr/lib/rpiota/` | 程式與網頁 |
| `/opt/app/` | 範例應用 `hello.py` |
| `/etc/rpiota/version`、`epoch` | 版本號與建置時間戳 |
| `/etc/rpiota/device-class` | `cm4` |
| `/etc/rpiota/health.units` | 新版本要全部 active 才保留的服務 |
| `/persistent/ota/` | 更新包與狀態 |

| Unit | 身分 | 啟動時機 |
|---|---|---|
| `rpiota-hello.service` | 動態使用者 | 開機 |
| `rpiota-web.service` | `rpiota` | 開機，port 8080 |
| `rpiota-apply.path` → `.service` | root | 出現 `pending.ota` |
| `rpiota-commit.service` | root | 開機；失敗就重開 |

## 建置時要留意

以下項目已確認：OK（2026-11-27）。

- `image-rota` 靠 `/etc/os-release` 的 `IG_SOURCE_DATE_EPOCH` 判斷是否重設該 slot 的 `/var`。查原始碼時沒找到由誰寫入，`install.sh` 會在缺少時補上。OTA 本身不比較新舊，而是刪掉目標 slot 的 `/persistent/slots/system_x/var/.updated`，讓 `/var` 一定重建。
- 若 `--check` 或建置回報 config、變數不認得，多半是推測錯的部分：`trait: hw:ethernet`、以 `-- IGconf_…=` 傳入的變數、`device.hostname` 與 `user1sudo`。把錯誤訊息留下來。

## 實機檢查

接好序列主控台（登入需要密碼，建置時設 `RPIOTA_PASSWORD`），準備可重燒的 SD 卡。

| # | 做什麼 | 應該看到 | 結果 |
|---|---|---|---|
| 1 | 燒映像開機 | `findmnt /` 指向 system A；`http://rpiota.local:8080` 顯示版本 | OK |
| 2 | `journalctl -fu rpiota-hello` | 每 3 秒一行 `Hello OTA <版本>` | OK |
| 3 | `sudo reboot "0 tryboot"`，再一般重開 | 先開到 B，再回到 A | OK |
| 4 | 建新版本、上傳、按 `Update` | 自動重開到 B，log 顯示 `Update succeeded.`，版本號改變；再重開仍在 B | OK |
| 5 | 上傳比目前舊的包、按 `Update`，開機後 `journalctl -b -u slot-var-reset` | 版本號退回舊版，`slot-var-reset` 有執行 | OK |
| 6 | 在 `image/systemd/health.units` 加一個不存在的服務，建版更新（測完移除） | 約 3 分鐘後回舊版，health check failed | OK |
| 7 | 寫入中拔電源 | 拔電前的版本正常開機，顯示上次更新中斷，可再上傳 | OK |
| 8 | 更新成功後記下 `sudo cat /bootfs/autoboot.txt`，立刻拔電源再開機 | 仍開新版本；`autoboot.txt` 內容和拔電前相同 | OK |
| 9 | 接第 8 步退回舊版、寫入中拔電源，再開機 | 開拔電前的版本；`autoboot.txt` 不是空的 | OK |

除錯：

```bash
journalctl -u rpiota-apply -u rpiota-commit -b
cat /persistent/ota/state.json
```
