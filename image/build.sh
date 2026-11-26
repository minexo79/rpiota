#!/usr/bin/env bash
# 建置 OTA 映像並打包更新檔。在 Debian／Raspberry Pi OS 上以一般使用者執行。
#
#   取得鎖定版本的 rpi-image-gen ─> 建置 ─> boot.sparse, system.sparse ─> update-版本.ota
#
# 用法：
#   image/build.sh --deps    安裝建置需要的套件（會用 sudo）
#   image/build.sh --check   只檢查 layer 格式，不建置
#   RPIOTA_VERSION=1.0.0 RPIOTA_SSH_PUBKEY=~/.ssh/id_ed25519.pub image/build.sh
#
# 環境變數：
#   RPIOTA_VERSION      版本號（建置必填）
#   RPIOTA_SSH_PUBKEY   SSH 公鑰檔 ┐ 兩者至少給一個
#   RPIOTA_PASSWORD     pi 的密碼  ┘ （大小寫、數字、@$!%*?& 各一，8 字以上）
#   RPIOTA_IG_DIR       rpi-image-gen 位置，預設 ~/rpi-image-gen-ota
#   RPIOTA_WORK         建置目錄，預設 ~/rpi-ota-work
#   RPIOTA_OUT          更新檔輸出目錄，預設 <專案>/out
set -euo pipefail

IG_REPO=https://github.com/raspberrypi/rpi-image-gen
IG_COMMIT=85a9345960c6e96a8b9269988ed5629b6f9e87d0
NAME=rpiota   # 要和 config/ota.yaml 的 image.name 相同

root="$(cd "$(dirname "$0")/.." && pwd)"
ig=${RPIOTA_IG_DIR:-$HOME/rpi-image-gen-ota}
work=${RPIOTA_WORK:-$HOME/rpi-ota-work}
out=${RPIOTA_OUT:-$root/out}

die() { printf '錯誤：%s\n' "$*" >&2; exit 1; }

fetch_ig() {
  command -v git >/dev/null || die "請先安裝 git"
  if [ ! -d "$ig/.git" ]; then
    git init -q "$ig"
    git -C "$ig" remote add origin "$IG_REPO"
  fi
  if [ "$(git -C "$ig" rev-parse -q --verify HEAD || true)" != "$IG_COMMIT" ]; then
    git -C "$ig" fetch -q --depth 1 origin "$IG_COMMIT"
    git -C "$ig" checkout -q --detach "$IG_COMMIT"
  fi
}

case "${1:-}" in
  --deps)
    fetch_ig
    (cd "$ig" && sudo ./install_deps.sh)
    exit ;;
  --check)
    fetch_ig
    "$ig/rpi-image-gen" metadata --lint "$root/image/layer/rpiota.yaml"
    echo "layer 格式檢查通過"
    exit ;;
  "") ;;
  *) die "不認得的參數 $1（可用 --deps、--check）" ;;
esac

[ -n "${RPIOTA_VERSION:-}" ] || die "請設定 RPIOTA_VERSION"
[[ $RPIOTA_VERSION =~ ^[A-Za-z0-9._+-]{1,64}$ ]] || die "RPIOTA_VERSION 只能用英數字與 . _ + -，最長 64 字"
login=()
if [ -n "${RPIOTA_SSH_PUBKEY:-}" ]; then
  [ -f "$RPIOTA_SSH_PUBKEY" ] || die "找不到公鑰 $RPIOTA_SSH_PUBKEY"
  login+=("IGconf_ssh_pubkey_user1=$(head -n 1 "$RPIOTA_SSH_PUBKEY")")
fi
if [ -n "${RPIOTA_PASSWORD:-}" ]; then
  login+=("IGconf_device_user1pass=$RPIOTA_PASSWORD")
fi
[ ${#login[@]} -gt 0 ] || die "請設定 RPIOTA_SSH_PUBKEY 或 RPIOTA_PASSWORD，否則映像無法登入"
[[ $root != *" "* ]] || die "專案路徑不能有空白：$root"
for tool in python3 zstd; do
  command -v "$tool" >/dev/null || die "請先安裝 $tool"
done

fetch_ig
epoch=$(date +%s)
mkdir -p "$work" "$out"
marker="$work/.build-start"
touch "$marker"

"$ig/rpi-image-gen" build -S "$root/image" -B "$work" -c ota.yaml -- \
  "IGconf_rpiota_src=$root/ota" \
  "IGconf_rpiota_version=$RPIOTA_VERSION" \
  "IGconf_rpiota_epoch=$epoch" \
  "${login[@]}"

images="$work/image-$NAME"
for file in boot.sparse system.sparse; do
  # 必須是這次建置產生的，避免打包到舊檔
  [ "$images/$file" -nt "$marker" ] || die "沒有新的 $images/$file"
done

bundle="$out/update-$RPIOTA_VERSION.ota"
PYTHONPATH="$root/ota" PYTHONDONTWRITEBYTECODE=1 python3 -m rpiota.bundle \
  --image-dir "$images" --version "$RPIOTA_VERSION" --epoch "$epoch" --out "$bundle"

printf '\n燒錄映像：%s\n更新檔：  %s\n' "$images/$NAME.img" "$bundle"
