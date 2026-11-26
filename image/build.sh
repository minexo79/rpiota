#!/usr/bin/env bash
# 建置 OTA 映像並打包更新檔。在 Debian／Raspberry Pi OS 上以一般使用者執行。
#
#   取得鎖定版本的 rpi-image-gen ─> 建置 ─> boot.sparse, system.sparse ─> update-版本.ota
#                                      rpiota.img.zst ─> rpiota-版本.img.zst
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
#   RPIOTA_IG_DIR       rpi-image-gen 位置，預設 <專案>/build/rpi-image-gen-ota
#   RPIOTA_WORK         建置目錄，預設 <專案>/build/rpi-ota-work
#   RPIOTA_OUT          燒錄映像與更新檔輸出目錄，預設 <專案>/build
set -euo pipefail

IG_REPO=https://github.com/raspberrypi/rpi-image-gen
IG_COMMIT=85a9345960c6e96a8b9269988ed5629b6f9e87d0
NAME=rpiota   # 要和 config/ota.yaml 的 image.name 相同

root="$(cd "$(dirname "$0")/.." && pwd)"
ig=${RPIOTA_IG_DIR:-$root/build/rpi-image-gen-ota}
work=${RPIOTA_WORK:-$root/build/rpi-ota-work}
out=${RPIOTA_OUT:-$root/build}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

fetch_ig() {
  command -v git >/dev/null || die "please install git first"
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
    echo "Layer lint passed"
    exit ;;
  "") ;;
  *) die "unknown argument $1 (use --deps or --check)" ;;
esac

[ -n "${RPIOTA_VERSION:-}" ] || die "RPIOTA_VERSION is not set"
[[ $RPIOTA_VERSION =~ ^[A-Za-z0-9._+-]{1,64}$ ]] || die "RPIOTA_VERSION may only contain letters, digits and . _ + -, up to 64 characters"
login=()
if [ -n "${RPIOTA_SSH_PUBKEY:-}" ]; then
  [ -f "$RPIOTA_SSH_PUBKEY" ] || die "public key not found: $RPIOTA_SSH_PUBKEY"
  login+=("IGconf_ssh_pubkey_user1=$(head -n 1 "$RPIOTA_SSH_PUBKEY")")
fi
if [ -n "${RPIOTA_PASSWORD:-}" ]; then
  login+=("IGconf_device_user1pass=$RPIOTA_PASSWORD")
fi
[ ${#login[@]} -gt 0 ] || die "set RPIOTA_SSH_PUBKEY or RPIOTA_PASSWORD, otherwise you cannot log in to the image"
[[ $root != *" "* ]] || die "project path must not contain spaces: $root"
for tool in python3 zstd; do
  command -v "$tool" >/dev/null || die "please install $tool first"
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
  [ "$images/$file" -nt "$marker" ] || die "no newly built $images/$file"
done

# deploy 目錄名稱隨專案的 git 版本改變，只取這次建置產生的壓縮映像
zst=
for file in "$work"/deploy-*/"$NAME.img.zst"; do
  if [ "$file" -nt "$marker" ]; then zst=$file; fi
done
[ -n "$zst" ] || die "no newly built $work/deploy-*/$NAME.img.zst"
flash="$out/$NAME-$RPIOTA_VERSION.img.zst"
cp "$zst" "$flash"

bundle="$out/update-$RPIOTA_VERSION.ota"
PYTHONPATH="$root/ota" PYTHONDONTWRITEBYTECODE=1 python3 -m rpiota.bundle \
  --image-dir "$images" --version "$RPIOTA_VERSION" --epoch "$epoch" --out "$bundle"

printf '\nFlash image: %s\nUpdate file: %s\n' "$flash" "$bundle"
