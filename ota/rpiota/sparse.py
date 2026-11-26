"""讀取 rpi-image-gen 輸出的 boot.sparse、system.sparse，寫進 Pi 的分割區。

這兩個檔案由 genimage 產生，格式名稱是「Android sparse」（略過空白區塊的映像格式），
程式只跑在 Pi 上，和 Android 裝置無關。邊讀邊寫，輸入不需要能 seek。

檔頭 28 bytes ──> [chunk 檔頭 12 bytes + 資料] × N
chunk：RAW 照抄、FILL 重複 4 bytes、DONT_CARE 跳過、CRC32 忽略
"""
import struct

MAGIC = 0xED26FF3A
HEADER = struct.Struct("<IHHHHIIII")
CHUNK = struct.Struct("<HHII")
RAW, FILL, DONT_CARE, CRC32 = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4
STEP = 1 << 20


def _read(stream, size):
    data = stream.read(size)
    while len(data) < size:
        more = stream.read(size - len(data))
        if not more:
            raise ValueError("incomplete sparse data")
        data += more
    return data


def _header(stream):
    magic, major, _, file_header_size, chunk_header_size, block, blocks, chunks, _ = (
        HEADER.unpack(_read(stream, HEADER.size)))
    if (magic != MAGIC or major != 1 or file_header_size < HEADER.size
            or chunk_header_size < CHUNK.size or not block or block % 4):
        raise ValueError("image is not in sparse format")
    _read(stream, file_header_size - HEADER.size)
    return chunk_header_size, block, blocks, chunks


def raw_size(path):
    with open(path, "rb") as stream:
        _, block, blocks, _ = _header(stream)
    return block * blocks


def _data(stream, kind, length):
    """依序產生 RAW、FILL chunk 要寫入的資料，每段最多 STEP bytes。"""
    pattern = _read(stream, 4) * (STEP // 4) if kind == FILL else None
    for offset in range(0, length, STEP):
        step = min(length - offset, STEP)
        yield _read(stream, step) if kind == RAW else pattern[:step]


# 寫入流程（任何檢查不過就丟 ValueError）：
#
#   讀檔頭 ──> 展開大小 > limit？ ──是──> 中止（尚未寫入任何資料）
#        │否
#   ┌─> 讀 chunk 檔頭
#   │     ├─ CRC32 ──> 讀掉資料，換下一個
#   │     └─ 檢查範圍與資料長度 ──> seek 到目前位置
#   │           ├─ RAW ───────> 每次最多 STEP bytes 照抄
#   │           ├─ FILL ──────> 4 bytes 重複寫滿
#   │           └─ DONT_CARE ─> 不寫（保留分割區原內容）
#   └──── 位置往後移，直到所有 chunk 讀完
#   最後位置 == 展開大小？ ──否──> 中止
def write(stream, out, limit, progress=None):
    """把 sparse 串流寫進 out，回傳展開後大小；超過 limit 或格式錯誤丟 ValueError。

    progress(已處理, 總量)：每寫一段呼叫一次，單位是展開後的 bytes。
    """
    chunk_header_size, block, blocks, chunks = _header(stream)
    total = block * blocks
    if total > limit:
        raise ValueError("image is larger than the partition")
    position = 0
    for _ in range(chunks):
        kind, _, count, chunk_bytes = CHUNK.unpack(_read(stream, CHUNK.size))
        _read(stream, chunk_header_size - CHUNK.size)
        length, payload = count * block, chunk_bytes - chunk_header_size
        if kind == CRC32:
            _read(stream, payload)
            continue
        if position + length > total:
            raise ValueError("chunk exceeds the image size")
        expected = {RAW: length, FILL: 4, DONT_CARE: 0}.get(kind)
        if payload != expected:
            raise ValueError("chunk length mismatch")
        out.seek(position)
        if kind == DONT_CARE:
            position += length
            if progress:
                progress(position, total)
            continue
        for data in _data(stream, kind, length):
            out.write(data)
            position += len(data)
            if progress:
                progress(position, total)
    if position != total:
        raise ValueError("total block count mismatch")
    return total
