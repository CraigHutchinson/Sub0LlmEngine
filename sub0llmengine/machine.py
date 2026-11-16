"""Facts about this machine. Bench history is kept per machine id (hardware, not the host name): every bound depends on it."""
import platform
import re
import subprocess

from . import config


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
        name, total, used, driver = [x.strip() for x in out.split(",")]
        return {"name": name, "vramMiB": int(total), "usedMiB": int(used), "driver": driver}
    except Exception:
        return None


def vramUsed():
    g = gpu()
    return g["usedMiB"] if g else None


def _ps(expr):
    return subprocess.run(["powershell", "-NoProfile", "-c", expr], capture_output=True, text=True, timeout=20).stdout.strip()


def cpu():
    if config.IS_WINDOWS:
        try:
            return _ps("(Get-CimInstance Win32_Processor).Name")
        except Exception:
            pass
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "cpu"


def ramGiB():
    try:
        if config.IS_WINDOWS:
            return round(int(_ps("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")) / 2**30)
        with open("/proc/meminfo") as f:
            return round(int(f.readline().split()[1]) / 2**20)
    except Exception:
        return None


_cached = None


def info():
    global _cached
    if _cached is None:
        g = gpu()
        c = cpu()
        short = re.sub(r"\(R\)|\(TM\)|Intel|AMD|Core|CPU|Processor|@.*", "", c)
        gname = (g["name"].replace("NVIDIA", "").replace("GeForce", "") + " %dG" % round(g["vramMiB"] / 1024)) if g else "nogpu"
        parts = [short, gname, "%dG" % (ramGiB() or 0)]
        mid = "_".join(re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-") for p in parts)
        _cached = {"id": mid, "cpu": c, "gpu": g, "ramGiB": ramGiB(), "os": platform.system() + " " + platform.release()}
    return _cached
