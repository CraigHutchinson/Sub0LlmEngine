"""Small cross-process benchmark status file. A heartbeat is not proof of forward progress."""
import ctypes
import json
import os
import time

from . import config


def cpu_seconds(pid):
    """Sample child CPU consumption without launching a monitoring subprocess."""
    try:
        if os.name == "nt":
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            try:
                creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
                if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
                    return None
                ticks = lambda t: (t.dwHighDateTime << 32) + t.dwLowDateTime
                return (ticks(kernel_time) + ticks(user_time)) / 10_000_000
            finally:
                kernel.CloseHandle(handle)
        with open("/proc/%d/stat" % pid) as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def write(**state):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    path = os.path.join(config.STATE_DIR, "bench-activity.json")
    state.update(heartbeatAt=time.time(), ownerPid=os.getpid())
    tmp = path + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    # On Windows the rename fails while a reader (the page's poll, an indexer) has the file open. A heartbeat must never
    # fail a bench: retry briefly, then skip this beat.
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass


def read():
    state = config.loadJson(os.path.join(config.STATE_DIR, "bench-activity.json"), {})
    if state:
        state["heartbeatAgeSeconds"] = max(0, round(time.time() - state["heartbeatAt"], 1))
    return state
