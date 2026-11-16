"""llama.cpp: llama-server for serving, llama-batched-bench for the speed / context / concurrency measurements."""
import datetime
import os
import re
import subprocess

from .. import config
from . import Backend

EXE = ".exe" if config.IS_WINDOWS else ""
ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|")


class LlamaCpp(Backend):
    name = "llamacpp"

    def binary(self, cfg, name):
        path = os.path.join(cfg.get("binDir") or "", name + EXE)
        if not os.path.isfile(path):
            raise SystemExit("no %s at %s: set 'binDir' in %s" % (name, path, config.writableLayer()))
        return path

    def common(self, cfg):
        """Placement, memory and compute flags shared by the server and the bench."""
        a = ["-ngl", str(cfg.get("gpuLayers", 99))]
        if cfg.get("nCpuMoe") is not None:
            a += ["-ncmoe", str(cfg["nCpuMoe"])]
        a += ["-fa", str(cfg.get("flashAttn", "on")), "-ctk", cfg.get("cacheTypeK", "q8_0"), "-ctv", cfg.get("cacheTypeV", "q8_0")]
        a += ["-b", str(cfg.get("batch", 2048)), "-ub", str(cfg.get("ubatch", 512)), "-t", str(cfg.get("threads", -1))]
        if not cfg.get("mmap", False):
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
            if os.path.isdir(os.path.join(d, ".git")):
                try:
                    out = subprocess.run(["git", "-C", d, "describe", "--tags", "--always"], capture_output=True, text=True, timeout=10).stdout.strip()
                    if out:
                        return "llama.cpp " + out
                except Exception:
                    pass
                break
        try:
            t = os.path.getmtime(os.path.join(bindir, "llama-server" + EXE))
            return "llama.cpp mtime-" + datetime.datetime.fromtimestamp(t).strftime("%Y%m%d")
        except OSError:
            return "llama.cpp unknown"
