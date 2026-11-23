"""Strata serving adapter. Its profile and profiling tools remain managed by Strata."""
from . import Backend, cliCommand, fileFingerprint, requiredFile


class Strata(Backend):
    name = "strata"

    def modelFormats(self):
        return ["strata", "gguf"]

    def selectionParams(self):
        return ("strataProfile",)

    def selectionFingerprint(self, cfg):
        return fileFingerprint(cfg, "strataProfile", "Strata run profile")

    def knobs(self):
        return [dict(id="strataProfile", type="file", change="load", identity=True,
                     affects=["speed", "context", "concurrency", "prefill"],
                     note="Strata run profile; tune backend-specific settings in Strata")]

    def serverCommand(self, cfg, modelPath):
        args = ["serve", "--profile", requiredFile(cfg, "strataProfile", "Strata run profile"),
                "--engine", "strata", "--host", cfg.get("host", "127.0.0.1"), "--port", cfg.get("port", 8092)]
        if cfg.get("slots") is not None:
            args += ["--parallel", cfg["slots"]]
        return cliCommand(requiredFile(cfg, "strataBin", "Strata CLI"), args)

    def benchCommand(self, cfg, modelPath, depth, ntg, bs):
        raise SystemExit("the shared sweep does not support Strata's native profiler; use Strata's profiling tools separately")

    def parseBench(self, text):
        raise SystemExit("Strata results are not normalized into the shared llama.cpp benchmark format")

    def buildLabel(self, cfg):
        return "Strata " + str(cfg.get("strataVersion") or "version unknown")
