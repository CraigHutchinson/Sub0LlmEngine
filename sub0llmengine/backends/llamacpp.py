"""llama.cpp: llama-server for serving, llama-batched-bench for the speed / context / concurrency measurements."""
import datetime
import os
import re
import subprocess

from .. import config
from . import Backend

from ..platform import EXE, localPath, IS_WINDOWS  # noqa: E402
ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|")


# The knobs, simplified: what each sets, when it can change, and which runtime axes it moves (see sub0llmengine/axes.py).
# change: "load" = fixed when llama-server loads (a change means a restart); "request" = per request.
# identity: part of a measured point (a bench record's params); benchAs: the bench's name for a server knob.
KNOBS = [
    dict(id="nCpuMoe", flag="-ncmoe", type="int", unit="layers", min=0, maxFact="expertLayers", change="load", identity=True,
         affects=["speed", "context"], note="expert layers kept in system RAM; each frees VRAM for context and costs decode speed"),
    dict(id="ctx", flag="-c", type="int", unit="tokens", min=256, step=256, change="load", identity=True,
         affects=["context", "concurrency"], note="total KV cache, shared by the slots (unified KV)"),
    dict(id="slots", flag="-np", type="int", unit="sequences", min=1, change="load", benchAs="B",
         affects=["concurrency"], note="requests served at once"),
    dict(id="ubatch", flag="-ub", type="int", unit="tokens", min=32, step=128, change="load", identity=True,
         affects=["prefill"], note="tokens per prompt-processing step; larger is faster prefill for more compute buffer VRAM"),
    dict(id="batch", flag="-b", type="int", unit="tokens", min=32, step=128, change="load", identity=True, affects=["prefill"]),
    dict(id="threads", flag="-t", type="int", unit="threads", min=-1, change="load", identity=True, affects=["speed", "prefill"],
         note="CPU threads for the CPU-resident experts; -1 is automatic"),
    dict(id="cacheTypeK", flag="-ctk", type="enum", values=["f16", "q8_0", "q4_0"], change="load", identity=True, affects=["context", "speed"]),
    dict(id="cacheTypeV", flag="-ctv", type="enum", values=["f16", "q8_0", "q4_0"], change="load", identity=True, affects=["context", "speed"]),
    dict(id="flashAttn", flag="-fa", type="enum", values=["on", "off", "auto"], change="load", identity=True, affects=["speed", "context"]),
    dict(id="kvUnified", flag="-kvu", type="bool", change="load", identity=True, affects=["concurrency"]),
    dict(id="mmap", flag="--no-mmap", type="bool", change="load", identity=True, affects=[], note="load time and RAM, not speed"),
    dict(id="kvUnifiedPerSlot", flag="--kv-unified-per-slot", type="int", unit="tokens", min=0, change="load", affects=["context"],
         note="context cap per slot inside the shared KV pool (newer builds only); unset: a slot may use the whole pool"),
    dict(id="gpuLayers", flag="-ngl", type="int", unit="layers", min=0, change="load", identity=True, affects=["speed", "context"]),
    dict(id="nPredict", field="n_predict", type="int", unit="tokens", min=-1, change="request", affects=[], note="output budget"),
    dict(id="idSlot", field="id_slot", type="int", min=-1, change="request", affects=[], note="pin a request to a slot (its KV)"),
    dict(id="cachePrompt", field="cache_prompt", type="bool", change="request", affects=["prefill"], note="reuse a cached prefix"),
]
# Moving a sequence's KV between configurations: llama-server saves and restores one slot to a file.
CONTEXT_TRANSFER = dict(method="slot-save-restore", serverFlag="--slot-save-path",
                        endpoints=["POST /slots/{id}?action=save", "POST /slots/{id}?action=restore", "POST /slots/{id}?action=erase"])


class LlamaCpp(Backend):
    name = "llamacpp"

    def selectionParams(self):
        return tuple(config.PARAM_KEYS)

    def knobs(self):
        return [dict(k) for k in KNOBS]

    def contextTransfer(self):
        return dict(CONTEXT_TRANSFER)

    _help = {}

    def hasFlag(self, cfg, flag):
        """Whether this build's llama-server accepts a flag (its --help, read once per binary folder)."""
        bindir = cfg.get("binDir") or ""
        if bindir not in self._help:
            try:
                self._help[bindir] = subprocess.run([self.binary(cfg, "llama-server"), "--help"], capture_output=True, text=True,
                                                    timeout=30, errors="replace").stdout
            except (SystemExit, OSError, subprocess.SubprocessError):
                self._help[bindir] = ""
        return flag in self._help[bindir]

    def binary(self, cfg, name):
        bindir = localPath(cfg.get("binDir") or "")
        path = os.path.join(bindir, name + EXE)
        if not os.path.isfile(path):
            hint = ""
            if not IS_WINDOWS and os.path.isfile(os.path.join(bindir, name + ".exe")):
                hint = (" (that folder has a Windows build: give this platform its own binDir in engine.local.linux.json, "
                        "or run the engine on Windows; with WSL's mirrored networking clients here reach it at 127.0.0.1)")
            raise SystemExit("no %s at %s: set 'binDir' in %s%s" % (name, path, config.writableLayer(), hint))
        return path

    def common(self, cfg):
        """Placement, memory and compute flags shared by the server and the bench."""
        a = ["-ngl", str(cfg.get("gpuLayers", 99))]
        if cfg.get("nCpuMoe") is not None:
            a += ["-ncmoe", str(cfg["nCpuMoe"])]
        a += ["-fa", str(cfg.get("flashAttn", "on")), "-ctk", cfg.get("cacheTypeK", "q8_0"), "-ctv", cfg.get("cacheTypeV", "q8_0")]
        a += ["-b", str(cfg.get("batch", 2048)), "-ub", str(cfg.get("ubatch", 512)), "-t", str(cfg.get("threads", -1))]
        if self.hasFlag(cfg, "--load-mode"):  # upstream replaced --no-mmap with -lm/--load-mode (late 2026)
            a += ["-lm", "mmap" if cfg.get("mmap", False) else "none"]
        elif not cfg.get("mmap", False):
            a.append("--no-mmap")
        if cfg.get("kvUnified", True):
            a.append("-kvu")
        return a

    def serverCommand(self, cfg, modelPath):
        cmd = [self.binary(cfg, "llama-server"), "-m", modelPath, "--host", cfg.get("host", "127.0.0.1"), "--port", str(cfg.get("port", 8092)),
               "-c", str(cfg.get("ctx", 32768)), "-np", str(cfg.get("slots", 4))] + self.common(cfg)
        cmd += ["--alias", cfg.get("alias", "local"), "--metrics", "--jinja"]
        if cfg.get("ctxCheckpoints") is not None:
            cmd += ["-ctxcp", str(cfg["ctxCheckpoints"])]
        if cfg.get("cacheRam") is not None:
            cmd += ["-cram", str(cfg["cacheRam"])]
        if cfg.get("kvUnifiedPerSlot"):
            if not self.hasFlag(cfg, "--kv-unified-per-slot"):
                raise SystemExit("kvUnifiedPerSlot is set but this build has no --kv-unified-per-slot (upstream since 2026-08, "
                                 "ggml-org/llama.cpp#24124): use a newer binDir or remove the key")
            cmd += ["--kv-unified-per-slot", str(cfg["kvUnifiedPerSlot"])]
        return cmd + [str(x) for x in cfg.get("extraArgs", [])]

    def benchCommand(self, cfg, modelPath, depth, ntg, bs):
        return [self.binary(cfg, "llama-batched-bench"), "-m", modelPath, "-c", str(cfg["ctx"])] + self.common(cfg) + \
               ["-npp", str(depth), "-ntg", str(ntg), "-npl", ",".join(str(b) for b in bs)]

    def parseBench(self, text):
        rows = {}
        for line in text.splitlines():
            m = ROW.match(line)
            if m:
                rows[int(m.group(3))] = {"ppTps": float(m.group(6)), "tgTps": float(m.group(8)), "sec": float(m.group(9))}
        return rows

    def buildLabel(self, cfg):
        """`git describe` of the source tree the binaries were built in, else the server binary's date."""
        bindir = cfg.get("binDir") or ""
        d = bindir
        for _ in range(5):
            d = os.path.dirname(d)
            if os.path.exists(os.path.join(d, ".git")):  # a directory, or a file in a git worktree
                try:
                    out = subprocess.run(["git", "-C", d, "describe", "--tags", "--always"], capture_output=True, text=True, timeout=10).stdout.strip()
                    if out:
                        return "llama.cpp " + out
                except Exception:
                    pass
                break
        try:
            t = os.path.getmtime(os.path.join(localPath(bindir), "llama-server" + EXE))
            return "llama.cpp mtime-" + datetime.datetime.fromtimestamp(t).strftime("%Y%m%d")
        except OSError:
            return "llama.cpp unknown"
