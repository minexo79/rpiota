"""主板、CPU、GPU、RAM 資訊；讀不到的項目回 unknown。

device-tree / meminfo / lscpu ──> read() ──> web 的 /api/status
"""
import subprocess

UNKNOWN = "unknown"
GPUS = {"brcm,bcm2711": "VideoCore VI"}  # device-tree compatible ─> GPU 型號


def _strings(path):
    """device-tree 檔案：以 NUL 結尾的字串清單。"""
    return [s for s in path.read_text(encoding="utf-8").split("\0") if s]


def _board(env):
    return _strings(env.model)[0]


def _cpu(env):
    # 固定語系，欄位名稱才不會被翻譯
    output = env.run(["env", "LC_ALL=C", "lscpu"])
    fields = {}
    for line in output.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    text = f"{fields['Model name']} × {fields['CPU(s)']}"
    if "CPU max MHz" in fields:
        text += f" @ {float(fields['CPU max MHz']) / 1000:.2f} GHz"
    return f"{text} ({fields['Architecture']})"


def _gpu(env):
    return next(GPUS[name] for name in _strings(env.compatible) if name in GPUS)


def _ram(env):
    """系統可用的總容量，比板子標示的略小。"""
    for line in env.meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return f"{int(line.split()[1]) / (1 << 20):.1f} GiB"
    return UNKNOWN


def read(env):
    info = {}
    for name, reader in (("board", _board), ("cpu", _cpu), ("gpu", _gpu), ("ram", _ram)):
        try:
            info[name] = reader(env)
        except (OSError, subprocess.SubprocessError, LookupError, ValueError,
                StopIteration):
            info[name] = UNKNOWN
    return info
