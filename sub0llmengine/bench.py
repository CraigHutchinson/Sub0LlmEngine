"""Bench sweeps and the per-machine history (bench/<machine>.jsonl, one record per (configuration, depth, B), failures included).

A record:
  {"ts", "machine", "backend", "build", "model", "params": {PARAM_KEYS...}, "depth", "ntg", "B",
   "outcome": "ok"|"oom"|"error"|"missing", "ppTps", "tgTps" (all sequences together), "tgPerSeq",
   "vramBaseMiB" (in use before the run: the desktop's share), "peakVramMiB", "wallSec", "note", "error"}
"""
import datetime
import itertools
import json
import os
import re
import subprocess
import threading
import time

from . import backends, config, machine, registry


def historyPath(mid=None):
    return os.path.join(config.BENCH_DIR, (mid or machine.info()["id"]) + ".jsonl")


def machines():
    if not os.path.isdir(config.BENCH_DIR):
        return []
    return sorted(f[:-6] for f in os.listdir(config.BENCH_DIR) if f.endswith(".jsonl"))


def append(records):
    os.makedirs(config.BENCH_DIR, exist_ok=True)
    with open(historyPath(), "a", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def history(mid=None):
    path = historyPath(mid)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class VramSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.peak = 0
        self.halt = threading.Event()

    def run(self):
        while not self.halt.is_set():
            v = machine.vramUsed()
            if v is not None:
                self.peak = max(self.peak, v)
            self.halt.wait(0.5)


def point(cfg, params, depth, ntg, bs, log=None, note=""):
    """One bench run: one configuration, several concurrencies. Appends and returns its records."""
    run = dict(cfg)
    run.update(params)
    be = backends.get(run)
    bs = [b for b in bs if be.fitsBench(run, depth, ntg, b)]
    if not bs:
        return []
    model, rid = registry.resolve(run)
    cmd = be.benchCommand(run, model, depth, ntg, bs)
    base = machine.vramUsed()
    sampler = VramSampler()
    sampler.start()
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    wall = time.time() - t0
    sampler.halt.set()
    sampler.join()
    text = proc.stdout + proc.stderr
    if log:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("$ " + " ".join(cmd) + "\n" + text + "\n")
    outcome = be.classifyFailure(proc.returncode, text)
    rows = be.parseBench(text)
    if outcome == "ok" and not rows:
        outcome = "error"
    err = ""
    if outcome != "ok":
        err = next((l.strip() for l in text.splitlines() if re.search(r"out of memory|allocation failed|error", l, re.I)), "")
    common = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "machine": machine.info()["id"], "backend": be.name,
              "build": be.buildLabel(run), "model": rid or os.path.basename(model), "params": {k: run.get(k) for k in config.PARAM_KEYS},
              "depth": depth, "ntg": ntg, "vramBaseMiB": base, "peakVramMiB": sampler.peak or None, "wallSec": round(wall, 1), "note": note}
    recs = []
    for b in bs:
        r = dict(common, B=b)
        if b in rows:
            r.update(outcome="ok", ppTps=rows[b]["ppTps"], tgTps=rows[b]["tgTps"], tgPerSeq=round(rows[b]["tgTps"] / b, 2))
        else:
            r.update(outcome=outcome if outcome != "ok" else "missing", error=err[:300])
        recs.append(r)
    append(recs)
    return recs


def paramsKey(params):
    return json.dumps({k: params.get(k) for k in config.PARAM_KEYS}, sort_keys=True)


def sweep(cfg, grid, log=None, progress=None, again=False, say=print):
    """grid: {param: [values]} for PARAM_KEYS, plus "depth": [..], "ntg": n, "B": [..], "note". Cartesian product of params x depth;
    the B list is one run per combination. Points already in the history are skipped unless `again`."""
    keys = [k for k in config.PARAM_KEYS if k in grid]
    ntg = int(grid.get("ntg", 128))
    known = set() if again else {(paramsKey(r["params"]), r["depth"], r["B"], r.get("ntg")) for r in history()}
    combos = list(itertools.product(*[grid[k] for k in keys], grid.get("depth", [2048])))
    out = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo[:-1]))
        depth = int(combo[-1])
        merged = dict(cfg)
        merged.update(params)
        pk = paramsKey(merged)
        bs = [int(b) for b in grid.get("B", [1]) if (pk, depth, int(b), ntg) not in known]
        label = " ".join("%s=%s" % kv for kv in params.items()) + " depth=%d" % depth
        if progress:
            progress(i, len(combos), label + " B=" + ",".join(map(str, bs)))
        if not bs:
            say("[%d/%d] already measured: %s" % (i + 1, len(combos), label))
            continue
        for r in point(cfg, params, depth, ntg, bs, log=log, note=grid.get("note", "")):
            say("[%d/%d] %s B=%d %s tg=%s tg/seq=%s pp=%s peak=%sMiB" % (i + 1, len(combos), label, r["B"], r["outcome"],
                r.get("tgTps", "-"), r.get("tgPerSeq", "-"), r.get("ppTps", "-"), r.get("peakVramMiB")))
            out.append(r)
    return out
