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


def fixtures():
    return {"bench/summary.json": benchSummary(), "backends/llamacpp_command.json": llamacppCommands(),
            "backends/native_command.json": nativeCommands()}


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
