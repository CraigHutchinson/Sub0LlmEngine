"""Engine backends. A backend turns a configuration into a server command and a bench command, and reads the bench's output.

Today: llamacpp (llama.cpp llama-server / llama-batched-bench). Planned: strata, sub0llm. The config key "backend" picks one.
"""


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


def get(cfg):
    name = cfg.get("backend", "llamacpp")
    if name == "llamacpp":
        from .llamacpp import LlamaCpp
        return LlamaCpp()
    raise SystemExit("unknown backend '%s' (available: llamacpp)" % name)
