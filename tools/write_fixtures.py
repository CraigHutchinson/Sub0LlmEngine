"""Writes the fixtures the C++ tests read from the Python reference (docs/SERVICE.md "Port order").

    python tools/write_fixtures.py          write tests/fixtures/
    python tools/write_fixtures.py --check  fail if the committed fixtures differ from what the reference produces
                                            (exit 77, "skipped", when the reference cannot be imported: no Sub0Platform checkout)

bench/summary.json describes the real bench history: the C++ contracts layer must parse the same file to the same numbers.
backends/llamacpp_command.json holds llama-server command lines the reference builds for a set of configs and build capabilities.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BENCH = os.path.join(ROOT, "bench", "ultra-9-275hx_rtx-5070-laptop-gpu-8g_63g.jsonl")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def benchSummary():
    rows = []
    with open(BENCH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    outcomes = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "source": "bench/" + os.path.basename(BENCH),
        "rows": len(rows),
        "outcomes": dict(sorted(outcomes.items())),
        "withExcluded": sum(1 for r in rows if r.get("excluded")),
        "withoutBackend": sum(1 for r in rows if "backend" not in r),
        "nullPeakVram": sum(1 for r in rows if r["peakVramMiB"] is None),
        "nullWallSec": sum(1 for r in rows if r["wallSec"] is None),
        "maxDepth": max(r["depth"] for r in rows),
        "maxConcurrency": max(r["B"] for r in rows),
        "sumTgTps": round(math.fsum(r["tgTps"] for r in rows if r.get("tgTps") is not None), 6),
        "sumPpTps": round(math.fsum(r["ppTps"] for r in rows if r.get("ppTps") is not None), 6),
        "distinctBuilds": len({r["build"] for r in rows}),
        "paramNames": sorted({k for r in rows for k in r["params"]}),
    }


# (name, config, build capabilities)
LLAMACPP_CASES = [
    ("defaults", {}, {}),
    ("serving-profile", {"port": 8092, "ctx": 131072, "slots": 4, "nCpuMoe": 32, "threads": 16, "ubatch": 512, "batch": 2048,
                         "cacheTypeK": "q8_0", "cacheTypeV": "q8_0", "flashAttn": "on", "kvUnified": True, "gpuLayers": 99,
                         "alias": "qwen35", "ctxCheckpoints": 8, "cacheRam": 8192}, {"loadMode": True}),
    ("old-build-mmap-off", {"mmap": False}, {}),
    ("old-build-mmap-on", {"mmap": True}, {}),
    ("load-mode-mmap-on", {"mmap": True}, {"loadMode": True}),
    ("no-unified-kv", {"kvUnified": False, "slots": 1, "ctx": 8192}, {}),
    ("per-slot-cap", {"kvUnifiedPerSlot": 16384, "slots": 8, "ctx": 131072}, {"kvUnifiedPerSlot": True}),
    ("per-slot-unsupported", {"kvUnifiedPerSlot": 16384}, {}),
    ("extra-args", {"extraArgs": ["--no-op-offload", "--ubatch-size", 256, "--temp", "0.6"], "host": "0.0.0.0", "port": 8093}, {}),
    ("nulls-mean-unset", {"nCpuMoe": None, "ctxCheckpoints": None, "kvUnifiedPerSlot": None}, {}),
]


def llamacppCommands():
    from sub0llmengine.backends.llamacpp import LlamaCpp
    cases = []
    for name, cfg, caps in LLAMACPP_CASES:
        backend = LlamaCpp()
        backend.binary = lambda c, n: "BIN/" + n
        backend.hasFlag = lambda c, flag, caps=caps: (
            (flag == "--load-mode" and caps.get("loadMode", False)) or (flag == "--kv-unified-per-slot" and caps.get("kvUnifiedPerSlot", False)))
        try:
            argv = backend.serverCommand(cfg, "M/model.gguf")
            error = False
        except SystemExit:
            argv, error = None, True
        cases.append({"name": name, "config": cfg,
                      "capabilities": {"loadMode": caps.get("loadMode", False), "kvUnifiedPerSlot": caps.get("kvUnifiedPerSlot", False)},
                      "executable": "BIN/llama-server", "model": "M/model.gguf", "argv": argv, "error": error})
    return {"cases": cases}


# (name, kind, config, host is Windows, COMSPEC)
NATIVE_CASES = [
    ("strata-defaults", "strata", {"strataBin": "S/strata.exe", "strataProfile": "P/profile.json"}, False, ""),
    ("strata-port-slots", "strata", {"strataBin": "S/strata.exe", "strataProfile": "P/profile.json", "port": 8123, "slots": 2, "host": "127.0.0.1"}, False, ""),
    ("strata-batch-launcher-windows", "strata", {"strataBin": "C:/Strata dir/strata.cmd", "strataProfile": "C:/p q/profile.json", "slots": 1},
     True, r"C:\Windows\system32\cmd.exe"),
    ("strata-batch-launcher-posix", "strata", {"strataBin": "S/strata.cmd", "strataProfile": "P/profile.json"}, False, ""),
    ("strata-exe-windows", "strata", {"strataBin": "C:/Strata/strata.exe", "strataProfile": "C:/p/profile.json"}, True, "cmd.exe"),
    ("basalt", "basalt", {"basaltBin": "B/basalt.exe", "basaltConfig": "C/basalt.json"}, False, ""),
    ("basalt-bat-windows", "basalt", {"basaltBin": "C:/Basalt/basalt.BAT", "basaltConfig": "C:/my config/basalt.json"}, True, ""),
]
QUOTING = ["plain", "a b", "", 'c"d', "e\\", "e\\ f", 'say "hi there"', "tab\tx", "C:\\Program Files\\x\\"]


def nativeCommands():
    import subprocess
    from sub0llmengine import backends as backendsPackage
    from sub0llmengine.backends import basalt, strata
    strata.requiredFile = lambda cfg, key, label: cfg[key]
    basalt.requiredFile = lambda cfg, key, label: cfg[key]
    saved = (backendsPackage.platform.IS_WINDOWS, os.environ.get("COMSPEC"))
    cases = []
    try:
        for name, kind, cfg, windows, comspec in NATIVE_CASES:
            backendsPackage.platform.IS_WINDOWS = windows
            if comspec:
                os.environ["COMSPEC"] = comspec
            else:
                os.environ.pop("COMSPEC", None)
            backend = strata.Strata() if kind == "strata" else basalt.Basalt()
            cases.append({"name": name, "kind": kind, "config": cfg, "windows": windows, "comspec": comspec,
                          "argv": backend.serverCommand(cfg, "unused")})
    finally:
        backendsPackage.platform.IS_WINDOWS = saved[0]
        if saved[1] is None:
            os.environ.pop("COMSPEC", None)
        else:
            os.environ["COMSPEC"] = saved[1]
    return {"cases": cases, "quoting": [{"in": a, "out": subprocess.list2cmdline([a])} for a in QUOTING]}


REGISTRY_MODELS = {
    "toy": {"name": "toy", "title": "Toy model for the registry fixture", "artifacts": [
        {"format": "gguf", "vendor": "unsloth", "variant": "Q8", "source": "hf:org/toy-GGUF#toy-Q8.gguf"},
        {"format": "gguf", "vendor": "unsloth", "variant": "Q4", "source": "hf:org/toy-GGUF#toy-Q4.gguf"},
        {"format": "gguf", "vendor": "local", "variant": "Tuned", "converter": "tune", "from": {"format": "gguf", "variant": "Q8"}},
        {"format": "gguf", "vendor": "org", "variant": "Split", "source": "hf:org/split-GGUF#split-0000[12]-of-00002.gguf"},
        {"format": "basalt", "vendor": "jesdga", "variant": "P1", "source": "hf:org/toy-Basalt#*.basalt"},
        {"format": "strata", "vendor": "strata-engine", "variant": "SQ",
         "source": ["hf:org/toy-Strata#toy-SQ.strata", "hf:org/toy-Strata#toy-Vision.strata"]},
        {"format": "strata", "vendor": "strata-engine", "variant": "SQ2",
         "source": ["hf:org/toy-Strata#toy-SQ.strata", "hf:org/toy-Strata#toy-Missing.strata"]},
        {"format": "other", "vendor": "x", "variant": "conv", "converter": "fake", "from": {"format": "gguf"}}]},
    "gone": {"name": "gone", "artifacts": [{"format": "gguf", "vendor": "org", "variant": "Q4", "source": "hf:org/gone-GGUF#gone.gguf"}]},
}
REGISTRY_ALIASES = {"toy": "hf/org/toy-GGUF@abc123def456#toy-Q8.gguf", "split": "hf/org/split-GGUF@d3d3d3d3d3d3", "vis": "hf/org/vis-GGUF@e4e4e4e4e4e4",
                    "multi": "hf/org/multi-GGUF@f5f5f5f5f5f5", "gone": "hf/org/gone-GGUF@a6a6a6a6a6a6"}
RESOLVE_REFS = ["toy", "hf/org/toy-GGUF@abc123def456", "hf/org/toy-GGUF@abc123def456#toy-Q8.gguf", "split", "vis", "multi",
                "hf/org/multi-GGUF@f5f5f5f5f5f5#b.gguf", "gone", "no-such-alias", "hf/org/none@000000000000"]
REQUESTS = [("toy", ["basalt", "gguf"], "", ""), ("toy", ["gguf"], "", ""), ("toy", ["gguf"], "Q4", ""), ("toy", ["gguf"], "Tuned", ""),
            ("toy", ["gguf"], "Split", ""), ("toy", ["strata"], "", ""), ("toy", ["strata"], "SQ2", ""), ("toy", ["other"], "", ""),
            ("toy", ["onnx"], "", ""), ("toy", ["gguf"], "", "nobody"), ("toy", ["strata", "gguf"], "", ""), ("nope", ["gguf"], "", ""),
            ("gone", ["gguf"], "", "")]


def registryFixture():
    """A tiny registry built with the reference tool, normalised so it is the same on every machine, with what the reference answers."""
    import shutil
    import tempfile
    sibling = os.path.join(os.path.dirname(ROOT), "Sub0LlmModelRegistry")
    if os.path.isdir(sibling) and sibling not in sys.path:
        sys.path.append(sibling)
    from sub0llmregistry import Registry, catalog
    from sub0llmregistry.store import Evicted
    tmp = tempfile.mkdtemp()
    try:
        reg = Registry(tmp)

        def add(folder, files, fmt, repo=None, **fields):
            full = os.path.join(tmp, *folder.split("/"))
            os.makedirs(full)
            for name in files:
                with open(os.path.join(full, name), "wb") as f:
                    f.write(b"x")
            src = {"provider": "hf", "repo": repo, "revision": folder.rsplit("/", 1)[1]} if repo else None
            m = reg.newManifest(full, fmt=fmt, source=src)
            if fields:
                m.update(fields)
                reg.writeManifest(full, m)

        add("hf/org/toy-GGUF/abc123def456", ["toy-Q8.gguf"], "gguf", "org/toy-GGUF")
        add("hf/org/toy-Basalt/b1b1b1b1b1b1", ["toy.basalt"], "basalt", "org/toy-Basalt")
        add("hf/org/toy-Strata/c2c2c2c2c2c2", ["toy-SQ.strata", "toy-Vision.strata"], "strata", "org/toy-Strata")
        add("hf/org/split-GGUF/d3d3d3d3d3d3", ["split-00001-of-00002.gguf", "split-00002-of-00002.gguf"], "gguf", "org/split-GGUF")
        add("hf/org/vis-GGUF/e4e4e4e4e4e4", ["vis-Q4.gguf", "mmproj.gguf"], "gguf", "org/vis-GGUF")
        add("hf/org/multi-GGUF/f5f5f5f5f5f5", ["a.gguf", "b.gguf"], "gguf", "org/multi-GGUF")
        add("hf/org/gone-GGUF/a6a6a6a6a6a6", ["gone.gguf"], "gguf", "org/gone-GGUF", evicted={"at": "2026-11-24T00:00:00", "bytes": 1})
        add("local/toy/Tuned/20261124", ["tuned.gguf"], "gguf", None, model="toy", variant="Tuned", vendor="local",
            derivedFrom="hf/org/toy-GGUF@abc123def456")
        for name, definition in REGISTRY_MODELS.items():
            os.makedirs(os.path.join(tmp, "models"), exist_ok=True)
            with open(os.path.join(tmp, "models", name + ".json"), "w", encoding="utf-8") as f:
                json.dump(definition, f)
        with open(os.path.join(tmp, "aliases.json"), "w", encoding="utf-8") as f:
            json.dump(REGISTRY_ALIASES, f)
        reg.index()
        index = json.load(open(os.path.join(tmp, "registry.json"), encoding="utf-8"))
        index["generated"] = "2026-11-24T00:00:00"
        index["root"] = "<root>"
        for entry in index["entries"].values():
            entry.pop("path", None)
            entry["created"] = "2026-11-24"

        def rel(path):
            return os.path.relpath(path, tmp).replace("\\", "/")

        def attempt(call):
            try:
                path, rid = call()
                return {"ok": True, "path": rel(path), "id": rid}
            except Evicted:
                return {"ok": False, "kind": "evicted"}
            except catalog.Unavailable:
                return {"ok": False, "kind": "unavailable"}
            except ValueError:
                return {"ok": False, "kind": "ambiguous"}
            except KeyError:
                return {"ok": False, "kind": "unknown"}

        expected = {
            "resolve": [dict(ref=r, **attempt(lambda r=r: reg.resolve(r, track=False))) for r in RESOLVE_REFS],
            "artifacts": {n: [{"format": a["format"], "variant": a.get("variant", ""), "state": a["state"], "id": a.get("id", "")}
                              for a in catalog.artifacts(reg, n, {})] for n in REGISTRY_MODELS},
            "requests": [dict(model=m, formats=f, variant=v, vendor=w, **attempt(lambda m=m, f=f, v=v, w=w: catalog.request(reg, m, f, variant=v or None, vendor=w or None)))
                         for m, f, v, w in REQUESTS],
        }
        out = {"registry/registry.json": index, "registry/expected.json": expected}
        for name, definition in REGISTRY_MODELS.items():
            out["registry/models/%s.json" % name] = definition
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fixtures():
    out = {"bench/summary.json": benchSummary(), "backends/llamacpp_command.json": llamacppCommands(),
           "backends/native_command.json": nativeCommands()}
    out.update(registryFixture())
    return out


def main():
    try:
        want = {name: json.dumps(value, indent=2) + "\n" for name, value in fixtures().items()}
    except ImportError as e:
        print("skipped: the Python reference cannot be imported (%s)" % e, file=sys.stderr)
        return 77 if "--check" in sys.argv else 1
    stale = []
    for name, text in want.items():
        path = os.path.join(FIXTURES, *name.split("/"))
        if "--check" in sys.argv:
            have = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            if have != text:
                stale.append(name)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("wrote", path)
    if stale:
        print("stale fixtures (run python tools/write_fixtures.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    if "--check" in sys.argv:
        print("fixtures are fresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
