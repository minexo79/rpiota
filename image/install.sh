#!/usr/bin/env bash
# 把 OTA 程式、設定與 systemd units 裝進映像的 rootfs（由 layer 的 customize hook 呼叫）。
#
#   ota/rpiota, ota/web         ─> /usr/lib/rpiota/
#   app                         ─> /opt/app/
#   版本、時間戳、機型          ─> /etc/rpiota/
#   systemd/                    ─> units、tmpfiles、watchdog
#
# 用法：install.sh <rootfs>
# 環境變數：IGconf_rpiota_src、IGconf_rpiota_version、IGconf_rpiota_epoch
set -euo pipefail

rootfs=${1:?缺少 rootfs 路徑}
src=${IGconf_rpiota_src:?}
version=${IGconf_rpiota_version:?}
epoch=${IGconf_rpiota_epoch:?}
units="$(cd "$(dirname "$0")" && pwd)/systemd"

lib="$rootfs/usr/lib/rpiota"
conf="$rootfs/etc/rpiota"
install -d -m 0755 "$lib/rpiota" "$lib/web" "$rootfs/opt/app" "$conf" \
  "$rootfs/etc/systemd/system" "$rootfs/etc/systemd/system.conf.d" \
  "$rootfs/usr/lib/tmpfiles.d"

install -m 0644 "$src"/rpiota/*.py "$lib/rpiota/"
install -m 0644 "$src"/web/* "$lib/web/"
install -m 0644 "$src"/../app/*.py "$rootfs/opt/app/"

printf '%s\n' "$version" > "$conf/version"
printf '%s\n' "$epoch" > "$conf/epoch"
printf 'cm4\n' > "$conf/device-class"
install -m 0644 "$units/health.units" "$conf/health.units"

install -m 0644 "$units"/*.service "$units"/*.path "$rootfs/etc/systemd/system/"
install -m 0644 "$units/rpiota.tmpfiles" "$rootfs/usr/lib/tmpfiles.d/rpiota.conf"
install -m 0644 "$units/watchdog.conf" "$rootfs/etc/systemd/system.conf.d/watchdog.conf"

# image-rota 的 slot-state 靠這個值判斷「映像較新」並重設該 slot 的 /var
release="$rootfs/usr/lib/os-release"
[ -f "$release" ] || release="$rootfs/etc/os-release"
grep -q '^IG_SOURCE_DATE_EPOCH=' "$release" ||
  printf 'IG_SOURCE_DATE_EPOCH=%s\n' "$epoch" >> "$release"

chroot "$rootfs" id rpiota >/dev/null 2>&1 ||
  chroot "$rootfs" useradd --system --user-group --no-create-home \
    --shell /usr/sbin/nologin rpiota

chroot "$rootfs" systemctl enable \
  rpiota-hello.service rpiota-web.service \
  rpiota-apply.path rpiota-commit.service avahi-daemon.service
