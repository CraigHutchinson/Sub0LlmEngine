"""Basalt serving adapter. Its config and profiling tools remain managed by Basalt."""
from . import Backend, cliCommand, fileFingerprint, requiredFile


class Basalt(Backend):
    name = "basalt"

    def modelFormats(self):
        return ["basalt"]

    def selectionParams(self):
        return ("basaltConfig",)

    def selectionFingerprint(self, cfg):
        return fileFingerprint(cfg, "basaltConfig", "Basalt server config")

    def knobs(self):
        return [dict(id="basaltConfig", type="file", change="load", identity=True,
                     affects=["speed", "context", "concurrency", "prefill"],
                     note="Basalt server config; tune backend-specific settings in Basalt")]

    def serverCommand(self, cfg, modelPath):
        args = ["serve", "--config", requiredFile(cfg, "basaltConfig", "Basalt server config")]
        return cliCommand(requiredFile(cfg, "basaltBin", "Basalt CLI"), args)

    def benchCommand(self, cfg, modelPath, depth, ntg, bs):
        raise SystemExit("the shared sweep does not support Basalt's native profiler; use Basalt's profiling tools separately")

    def parseBench(self, text):
        raise SystemExit("Basalt results are not normalized into the shared llama.cpp benchmark format")

    def buildLabel(self, cfg):
        return "Basalt " + str(cfg.get("basaltVersion") or "version unknown")
