"""Platform differences, from Sub0Platform (github.com/CraigHutchinson/Sub0Platform): Windows, Linux and WSL.

Everything that branches on the operating system goes through here, so the rest of the engine stays portable. The
work is done by the shared `sub0platform` package; this module only finds it and keeps the engine's names.
Install it (`pip install git+https://github.com/CraigHutchinson/Sub0Platform@v0.1.0`), or check it out beside this
repository (../Sub0Platform), which is found without installing.
"""
import os
import sys

try:
    import sub0platform  # noqa: F401
except ImportError:
    _SIBLING = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "Sub0Platform", "python")
    if not os.path.isdir(os.path.join(_SIBLING, "sub0platform")):
        raise ImportError("Sub0LlmEngine needs the sub0platform package: pip install "
                          "git+https://github.com/CraigHutchinson/Sub0Platform@v0.1.0, or clone Sub0Platform beside "
                          "this repository") from None
    sys.path.append(_SIBLING)

from sub0platform import env, fs, lock, paths, proc  # noqa: E402

IS_WINDOWS = env.IS_WINDOWS
IS_WSL = env.IS_WSL
# The config layer suffixes for this platform, most general first: engine.local.<name>.json files are applied in order.
NAMES = env.NAMES
EXE = env.EXE

spawnDetached = proc.spawnDetached
alive = proc.alive
terminate = proc.terminate
cpuSeconds = proc.cpuSeconds
atomicWrite = fs.atomicWrite
ExclusiveLock = lock.ExclusiveLock
lockOwner = lock.owner


def localPath(p):
    """A path as this platform reads it: a Windows drive path seen from WSL or Linux becomes /mnt/d/x, a WSL mount seen
    from Windows becomes D:/x; anything else is returned unchanged."""
    return paths.local(p, IS_WINDOWS)


def isForeignPath(p):
    """True for a Windows drive path on a system without WSL's /mnt mounts (it cannot be read here at all)."""
    return not IS_WINDOWS and not IS_WSL and paths.isDrivePath(p)
