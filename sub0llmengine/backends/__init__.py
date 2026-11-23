"""Engine backends. A backend turns a configuration into a server command and a bench command, and reads the bench's output.

The config key "backend" picks one. Native Strata and Basalt profiling is intentionally separate from the llama.cpp sweep.
"""
import hashlib
import os
import subprocess

from .. import platform


class Backend:
    name = "base"

    def selectionParams(self):
        """Backend-owned knobs required to reproduce an exported measured selection."""
        raise NotImplementedError

    def knobs(self):
        """The backend's knobs, simplified (see sub0llmengine/axes.py for the fields)."""
        raise NotImplementedError

    def contextTransfer(self):
        """How a sequence's KV can move from one running configuration to another, or None."""
        return None

    def selectionFingerprint(self, cfg):
        """A fingerprint for native config contents that affect the launched server."""
        return None

    def serverCommand(self, cfg, modelPath):
        """argv that serves an OpenAI-compatible API at cfg host:port."""
        raise NotImplementedError

    def benchCommand(self, cfg, modelPath, depth, ntg, bs):
        """argv that runs `len(bs)` concurrency levels at one placement."""
        raise NotImplementedError

    def parseBench(self, text):
        """{B: {"ppTps", "tgTps", "sec"}} from the bench's output."""
        raise NotImplementedError

    def classifyFailure(self, rc, text):
        """'ok' | 'oom' | 'error'."""
        if rc == 0:
            return "ok"
        t = text.lower()
        if "out of memory" in t or "resource allocation failed" in t or "failed to allocate" in t:
            return "oom"
        return "error"

    def buildLabel(self, cfg):
        return "unknown"

    def fitsBench(self, cfg, depth, ntg, b):
        """Whether `b` sequences of depth+ntg tokens fit the configured context."""
        return b * (depth + ntg) <= int(cfg.get("ctx", 0))


def requiredFile(cfg, key, label):
    path = platform.localPath(cfg.get(key) or "")
    if not path or not os.path.isfile(path):
        raise SystemExit("no %s at %s: set '%s' in engine.local.json or a config layer" % (label, path or "(unset)", key))
    return path


def fileFingerprint(cfg, key, label):
    with open(requiredFile(cfg, key, label), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def cliCommand(executable, args):
    """Run Windows batch launchers through cmd.exe; other executables are launched directly."""
    args = [str(x) for x in args]
    if platform.IS_WINDOWS and executable.lower().endswith((".cmd", ".bat")):
        command = subprocess.list2cmdline([executable] + args)
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
    return [executable] + args


def get(cfg):
    name = cfg.get("backend", "llamacpp")
    if name == "llamacpp":
        from .llamacpp import LlamaCpp
        return LlamaCpp()
    if name == "strata":
        from .strata import Strata
        return Strata()
    if name == "basalt":
        from .basalt import Basalt
        return Basalt()
    raise SystemExit("unknown backend '%s' (available: llamacpp, strata, basalt)" % name)
