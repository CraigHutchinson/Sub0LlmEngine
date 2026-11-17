"""Platform differences in one place: Windows, Linux and WSL (Linux on Windows).

Everything that branches on the operating system goes through here, so the rest of the engine stays portable and a
future shared tooling package can take this module whole (see docs/DESIGN.md, "Platform support").
"""
import os
import re
import signal
import subprocess

IS_WINDOWS = os.name == "nt"


def _isWsl():
    if IS_WINDOWS:
        return False
    try:
        with open("/proc/version", encoding="utf-8", errors="replace") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


IS_WSL = _isWsl()
# The config layer suffixes for this platform, most general first: engine.local.<name>.json files are applied in order.
NAMES = ["windows"] if IS_WINDOWS else (["linux", "wsl"] if IS_WSL else ["linux"])
EXE = ".exe" if IS_WINDOWS else ""
_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


def localPath(p):
    """A path as this platform reads it: a Windows drive path ("D:/x" or "D:\\x") seen from WSL or Linux becomes
    /mnt/d/x (WSL's mount of the Windows drives); anything else is returned unchanged."""
    if not p or IS_WINDOWS:
        return p
    m = _DRIVE.match(p)
    if not m:
        return p
    return "/mnt/" + m.group(1).lower() + "/" + p[3:].replace("\\", "/")


def isForeignPath(p):
    """True for a Windows drive path on a system without WSL's /mnt mounts (it cannot be read here at all)."""
    return bool(p) and not IS_WINDOWS and bool(_DRIVE.match(p)) and not IS_WSL


def spawnDetached(cmd, logFile):
    """Start a server that outlives this process, output to logFile. On Windows: its own process group, no console,
    below-normal priority so the desktop stays responsive. Elsewhere: its own session."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | 0x00004000 if IS_WINDOWS else 0
    with open(logFile, "w", encoding="utf-8") as lf:
        return subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                                start_new_session=not IS_WINDOWS)


def alive(pid):
    """Whether a process with this pid exists."""
    if IS_WINDOWS:  # OpenProcess + GetExitCodeProcess: no subprocess, exact pid
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists; invalid parameter: it does not
        try:
            code = wintypes.DWORD()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else


def terminate(pid):
    """Stop a process and its children: taskkill /T /F on Windows; SIGTERM to its session's process group elsewhere
    (spawnDetached made it a group leader), falling back to the process alone."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        os.kill(pid, signal.SIGTERM)
