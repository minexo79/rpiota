"""測試共用工具：產生 sparse 映像、更新包與指向暫存目錄的 Env。

make_sparse() ──> make_bundle() ──> make_env() ──> 各測試
"""
import io
import os
import struct
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rpiota import bundle, env as env_mod  # noqa: E402

BLOCK = 4096


def sparse_bytes(chunks, blocks=None):
    """chunks：("raw", bytes) / ("fill", 4bytes, 區塊數) / ("skip", 區塊數)。"""
    body, total = b"", 0
    for chunk in chunks:
        if chunk[0] == "raw":
            count, data, kind = len(chunk[1]) // BLOCK, chunk[1], 0xCAC1
        elif chunk[0] == "fill":
            count, data, kind = chunk[2], chunk[1], 0xCAC2
        else:
            count, data, kind = chunk[1], b"", 0xCAC3
        body += struct.pack("<HHII", kind, 0, count, 12 + len(data)) + data
        total += count
    header = struct.pack(
        "<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, BLOCK,
        total if blocks is None else blocks, len(chunks), 0)
    return header + body


def make_sparse(directory, name, blocks=8):
    raw = os.urandom(blocks * BLOCK)
    path = Path(directory) / name
    path.write_bytes(sparse_bytes([("raw", raw)]))
    return path, raw


def make_bundle(directory, version="2.0", epoch=2000, device_class="cm4", name="update.ota"):
    directory = Path(directory)
    boot, boot_raw = make_sparse(directory, "boot.sparse", 4)
    system, system_raw = make_sparse(directory, "system.sparse", 8)
    out = directory / name
    bundle.pack(boot, system, out, version=version, epoch=epoch, device_class=device_class)
    return out, boot_raw, system_raw


def rewrite_tar(source, out, edit):
    """讀出項目清單 [(名稱, 內容)]，交給 edit 修改後重新打包。"""
    with tarfile.open(source, "r:") as tar:
        members = [(m.name, tar.extractfile(m).read()) for m in tar]
    with tarfile.open(out, "w:") as tar:
        for name, data in edit(members):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return Path(out)


def make_env(directory):
    """分割區用一般檔案代替；active 是 slot a，other 是 slot b。

    label 用 hard link（Windows 建 symlink 要權限）。
    """
    root = Path(directory)
    calls = []

    def run(args):
        calls.append(list(args))
        if args[0] == "rpi-slot-tryboot":
            return "[all]\nboot_partition=3\n"
        return ""

    env = env_mod.Env(
        ota_dir=root / "ota", conf_dir=root / "conf", slot_dir=root / "slot",
        label_dir=root / "slot",
        autoboot=root / "autoboot.txt", run=run,
        persistent_slots=root / "slots",
        part_size=lambda path: Path(path).stat().st_size,
        model=root / "model", compatible=root / "compatible",
        meminfo=root / "meminfo")
    env.incoming.mkdir(parents=True)
    env.conf_dir.mkdir()
    (env.conf_dir / "version").write_text("1.0\n")
    (env.conf_dir / "device-class").write_text("cm4\n")
    (env.conf_dir / "health.units").write_text("ssh.service\nweb.service\n")
    (env.conf_dir / "epoch").write_text("1000\n")
    env.autoboot.write_text("old\n")
    for slot, filler in (("active", b"A"), ("other", b"B")):
        (env.slot_dir / slot).mkdir(parents=True)
        for part in ("boot", "system"):
            (env.slot_dir / slot / part).write_bytes(filler * (16 * BLOCK))
    for label, slot in (("system_a", "active"), ("system_b", "other")):
        os.link(env.slot_dir / slot / "system", env.label_dir / label)
        var = env.persistent_slots / label / "var"
        var.mkdir(parents=True)
        (var / ".updated").write_text("TIMESTAMP_NSEC=1\n")
    env.calls = calls
    return env
