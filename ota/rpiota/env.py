"""裝置上的路徑與外部指令；測試與本機試跑時換掉。

Env ──> state / apply / commit / web / hwinfo
"""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


def run_command(args):
    """執行外部指令並回傳 stdout，非零結束就丟例外。"""
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def device_size(path):
    with open(path, "rb") as device:
        return device.seek(0, os.SEEK_END)


@dataclass
class Env:
    ota_dir: Path = Path("/persistent/ota")
    conf_dir: Path = Path("/etc/rpiota")
    slot_dir: Path = Path("/dev/disk/by-slot")
    label_dir: Path = Path("/dev/disk/by-partlabel")
    autoboot: Path = Path("/bootfs/autoboot.txt")
    persistent_slots: Path = Path("/persistent/slots")
    run: Callable = run_command
    part_size: Callable = device_size
    model: Path = Path("/proc/device-tree/model")
    compatible: Path = Path("/proc/device-tree/compatible")
    meminfo: Path = Path("/proc/meminfo")

    @property
    def incoming(self):
        return self.ota_dir / "incoming"

    @property
    def part(self):
        """上傳中的檔案。"""
        return self.incoming / "upload.part"

    @property
    def upload(self):
        """已上傳完成；網頁接著送出套用要求，改名成 pending.ota。"""
        return self.incoming / "upload.ota"

    @property
    def pending(self):
        """已要求套用；systemd path unit 監看這個檔案。"""
        return self.incoming / "pending.ota"

    def conf(self, name):
        return (self.conf_dir / name).read_text(encoding="utf-8").strip()

    def version(self):
        try:
            return self.conf("version") or "unknown"
        except OSError:
            return "unknown"

    def slot(self, which="active"):
        """which（active：目前開機的、other：閒置的）是哪個 slot：a、b，判斷不出來回 ?。"""
        system = self.slot_dir / which / "system"
        if not system.exists():
            return "?"
        for name in ("a", "b"):
            label = self.label_dir / f"system_{name}"
            if label.exists() and os.path.samefile(label, system):
                return name
        return "?"
