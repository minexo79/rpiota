"""更新包 .ota：打包（PC）與檢查（裝置）。沒有簽章，只防傳輸損毀。

boot.sparse ──┐
              ├─ zstd 壓縮 ─> tar：manifest.json, boot.sparse.zst, system.sparse.zst
system.sparse ┘

用法：python3 -m rpiota.bundle --image-dir D --version V --epoch N --out F
"""
import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from . import sparse

MANIFEST_LIMIT = 64 * 1024
PARTS = ("boot", "system")
MANIFEST_NAME = "manifest.json"
DEVICE_CLASS = "cm4"
VERSION = re.compile(r"[A-Za-z0-9._+-]{1,64}")


class UpdateError(Exception):
    """更新包不能用；code 會寫進狀態檔，由網頁翻成訊息。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Image:
    file: str
    sha256: str
    raw_size: int


@dataclass(frozen=True)
class Manifest:
    format: int
    device_class: str
    version: str
    source_date_epoch: int
    boot: Image
    system: Image

    def image(self, part):
        return getattr(self, part)


def member_name(part):
    """分割區映像在更新包內的檔名。"""
    return f"{part}.sparse.zst"


def _hash(stream):
    digest = hashlib.sha256()
    while chunk := stream.read(1 << 20):
        digest.update(chunk)
    return digest.hexdigest()


def _check(condition):
    if not condition:
        raise UpdateError("bad_bundle")


def _parse(data):
    try:
        raw = json.loads(data)
        images = {}
        for part in PARTS:
            image = Image(**raw[part])
            _check(image.file == member_name(part) and isinstance(image.sha256, str)
                   and type(image.raw_size) is int and image.raw_size > 0)
            images[part] = image
        manifest = Manifest(**{**raw, **images})
    except (ValueError, KeyError, TypeError, RecursionError):
        raise UpdateError("bad_bundle") from None
    _check(manifest.format == 1 and type(manifest.source_date_epoch) is int
           and isinstance(manifest.device_class, str)
           and isinstance(manifest.version, str) and VERSION.fullmatch(manifest.version))
    return manifest


def _next(tar, name):
    member = tar.next()
    _check(member is not None and member.name == name and member.isreg())
    return member


def _read_manifest(tar):
    member = _next(tar, MANIFEST_NAME)
    _check(member.size <= MANIFEST_LIMIT)
    return _parse(tar.extractfile(member).read())


def read_manifest(path):
    """只讀第一個項目，給網頁顯示已上傳的版本。"""
    try:
        with tarfile.open(path, "r:") as tar:
            return _read_manifest(tar)
    except (tarfile.TarError, EOFError):
        raise UpdateError("bad_bundle") from None


def version_of(path):
    """更新包的版本號；讀不到就回 None。"""
    try:
        return read_manifest(path).version
    except (OSError, UpdateError):
        return None


def verify(path):
    """檢查項目名稱、順序與雜湊，不解到磁碟。"""
    try:
        with tarfile.open(path, "r:") as tar:
            manifest = _read_manifest(tar)
            for part in PARTS:
                member = _next(tar, member_name(part))
                if _hash(tar.extractfile(member)) != manifest.image(part).sha256:
                    raise UpdateError("bad_hash")
            _check(tar.next() is None)
            return manifest
    except (tarfile.TarError, EOFError):
        raise UpdateError("bad_bundle") from None


def pack(boot_sparse, system_sparse, out, *, version, epoch, device_class=DEVICE_CLASS):
    _check(VERSION.fullmatch(version))
    out = Path(out)
    with tempfile.TemporaryDirectory(dir=out.parent) as work:
        images, files = {}, []
        for part, source in zip(PARTS, (boot_sparse, system_sparse)):
            target = Path(work) / member_name(part)
            size = sparse.raw_size(source)
            subprocess.run(["zstd", "-q", "-T0", str(source), "-o", str(target)], check=True)
            with open(target, "rb") as stream:
                images[part] = Image(target.name, _hash(stream), size)
            files.append(target)
        manifest = Manifest(1, device_class, version, epoch, **images)
        data = json.dumps(asdict(manifest), indent=2).encode()
        temp = Path(work) / "bundle"
        with tarfile.open(temp, "w:", format=tarfile.GNU_FORMAT) as tar:
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            for file in files:
                tar.add(file, arcname=file.name)
        temp.replace(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description="打包 OTA 更新包")
    parser.add_argument("--image-dir", type=Path, required=True,
                        help="含 boot.sparse 與 system.sparse 的目錄")
    parser.add_argument("--version", required=True, help="要和映像內的 version 相同")
    parser.add_argument("--epoch", type=int, required=True,
                        help="映像的 IG_SOURCE_DATE_EPOCH")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device-class", default=DEVICE_CLASS)
    args = parser.parse_args(argv)
    try:
        pack(args.image_dir / "boot.sparse", args.image_dir / "system.sparse", args.out,
             version=args.version, epoch=args.epoch, device_class=args.device_class)
    except UpdateError:
        sys.exit("版本號只能用英數字與 . _ + -，最長 64 字")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"打包失敗：{error}")
    print(args.out)


if __name__ == "__main__":
    main()
