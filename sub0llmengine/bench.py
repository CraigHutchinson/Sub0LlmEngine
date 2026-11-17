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

from . import activity, backends, config, machine, platform, registry


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


def history(mid=None, everything=False):
    """The records; those marked "excluded" (measured while something else held the GPU or CPU, say) are left out unless
    `everything`. Records are never deleted: excluding keeps the evidence and turns the point back into a gap to re-measure."""
    path = historyPath(mid)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    return recs if everything else [r for r in recs if not r.get("excluded")]


def exclude(since, until, reason, note=None, mid=None):
    """Mark records with since <= ts <= until (ISO text, and with this note when given) as excluded. Returns how many."""
    path = historyPath(mid)
    recs = history(mid, everything=True)
    n = 0
    for r in recs:
        if since <= r["ts"] <= until and (note is None or r.get("note") == note) and not r.get("excluded"):
            r["excluded"] = reason
            n += 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    return n


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


class GpuLock:
    """One bench at a time across processes (the CLI and the page's job runner both bench): out/bench.lock, created exclusively.
    Never steal a lock on age alone: an extended-context run can legitimately take hours. A lock whose owner process no
    longer exists (a crashed bench) is set aside as bench.lock.stale-<pid> and taken; a live owner, or a reused pid, is
    waited for (the safe side)."""
    path = os.path.join(config.STATE_DIR, "bench.lock")

    def __enter__(self):
        self._lock = platform.ExclusiveLock(self.path, onWait=lambda owner: activity.write(
            phase="waiting-lock", lockOwner=owner,
            message="Waiting for benchmark lock; age alone does not prove its owner has exited."))
        self._lock.__enter__()
        return self

    def __exit__(self, *exc):
        self._lock.__exit__(*exc)


def point(cfg, params, depth, ntg, bs, log=None, note="", timeout=None):
    """One bench run: one configuration, several concurrencies. Appends and returns its records."""
    run = dict(cfg)
    run.update(params)
    be = backends.get(run)
    bs = [b for b in bs if be.fitsBench(run, depth, ntg, b)]
    if not bs:
        return []
    model, rid = registry.resolve(run)
    cmd = be.benchCommand(run, model, depth, ntg, bs)
    with GpuLock():
        base = machine.vramUsed()
        sampler = VramSampler()
        sampler.start()
        t0 = time.time()
        timed_out = False
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            last_bytes, last_output = 0, None
            while True:
                try:
                    text, _ = proc.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired as e:
                    output = e.output or b""
                    output = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
                    if len(output) != last_bytes:
                        last_output, last_bytes = time.time(), len(output)
                    wall = time.time() - t0
                    activity.write(phase="running", pid=proc.pid, startedAt=t0, elapsedSeconds=round(wall, 1),
                                   cpuSeconds=activity.cpu_seconds(proc.pid), outputBytes=last_bytes,
                                   lastOutputAt=last_output, lastLine=output.strip().splitlines()[-1:] or [],
                                   depth=depth, B=bs, ntg=ntg, ctx=run["ctx"], timeoutSeconds=timeout)
                    if timeout and wall >= timeout:
                        timed_out = True
                        proc.kill()
                        text, _ = proc.communicate()
                        break
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.communicate()
            wall = time.time() - t0
            sampler.halt.set()
            sampler.join()
    if log:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("$ " + " ".join(cmd) + "\n" + text + "\n")
    outcome = "timeout" if timed_out else be.classifyFailure(proc.returncode, text)
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
    activity.write(phase="finished", pid=proc.pid, elapsedSeconds=round(wall, 1), outcome=outcome,
                   recordsWritten=len(recs), finishedAt=time.time(), depth=depth, B=bs, ntg=ntg, ctx=run["ctx"])
    return recs


def paramsKey(params):
    return json.dumps({k: params.get(k) for k in config.PARAM_KEYS}, sort_keys=True)


def scopedHistory(cfg, records, ntg):
    """No model/build/output-length substitutions when deciding what has been measured."""
    be = backends.get(cfg)
    path, rid = registry.resolve(cfg)
    identity = {"machine": machine.info()["id"], "model": rid or os.path.basename(path), "backend": be.name, "build": be.buildLabel(cfg)}
    return [r for r in records if not r.get("excluded") and r.get("ntg") == ntg and all(r.get(k) == v for k, v in identity.items())]


def sweep(cfg, grid, log=None, progress=None, again=False, say=print):
    """grid: {param: [values]} for PARAM_KEYS, plus "depth": [..], "ntg": n, "B": [..], "note". Cartesian product of params x depth;
    the B list is one run per combination. Points already in the history are skipped unless `again`."""
    keys = [k for k in config.PARAM_KEYS if k in grid]
    ntg = int(grid.get("ntg", 128))
    known = set() if again else {(paramsKey(r["params"]), r["depth"], r["B"], r.get("ntg")) for r in scopedHistory(cfg, history(), ntg)}
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


# ---- auto: fill the gaps of a view ------------------------------------------------------------------------------------------------
# Memory grows as fewer MoE layers stay on the CPU, as context and batches grow (allocated at load) and as more sequences hold
# deeper contexts (measured: 256k context and 36 CPU layers ran B=1,2 at depth 8192 and ran out of memory at B=4,8 in the same
# run). A point is its params plus "_B" and "_depth"; one needs at least as much memory as another when it is no lighter on
# any of these axes and equal on the rest that matter for memory.
MEM_DIR = {"nCpuMoe": -1, "ctx": 1, "ubatch": 1, "batch": 1, "_B": 1, "_depth": 1}
FEAS_SAME = ["cacheTypeK", "cacheTypeV", "flashAttn", "kvUnified", "mmap", "gpuLayers"]


def memPoint(params, depth, b):
    return dict(params, _depth=depth, _B=b)


def recPoint(r):
    return memPoint(r["params"], r["depth"], r["B"])


def needsAtLeast(a, b):
    """Point `a` needs at least as much memory as point `b` (a missing "_B"/"_depth" counts as 0, so plain params compare
    on placement and buffers alone)."""
    if any(a.get(k) != b.get(k) for k in FEAS_SAME):
        return False
    try:
        return all(d * (float(a.get(k) or 0) - float(b.get(k) or 0)) >= 0 for k, d in MEM_DIR.items())
    except (TypeError, ValueError):
        return False


# Recency: the memory edge moves with what the desktop holds, and a run can fail for reasons outside the configuration (another
# process on the GPU, a driver hiccup). A failure is superseded once HEAL_RUNS later runs (distinct timestamps) of configurations
# needing at least as much memory worked: it then neither infers failures elsewhere, nor flags a contradiction, nor marks a cell.
HEAL_RUNS = 2


def superseded(records, model=None):
    """Timestamps+points of out-of-memory records that later successes have erased: {(ts, paramsKey, depth, B)}."""
    recs = [r for r in records if (model is None or r.get("model") == model) and r["outcome"] in ("ok", "oom")]
    oks = [r for r in recs if r["outcome"] == "ok"]
    out = set()
    for r in recs:
        if r["outcome"] != "oom":
            continue
        later = {o["ts"] for o in oks if o["ts"] > r["ts"] and o.get("model") == r.get("model") and needsAtLeast(recPoint(o), recPoint(r))}
        if len(later) >= HEAL_RUNS:
            out.add(recKey(r))
    return out


def recKey(r):
    return (r["ts"], paramsKey(r["params"]), r["depth"], r["B"])


def effective(records, model=None):
    """The records inference should trust: superseded failures removed."""
    gone = superseded(records, model)
    return [r for r in records if r["outcome"] != "oom" or recKey(r) not in gone]


def predict(params, depth, bs, model, records):
    """For the group (params, depth, every B in bs): 'ok' when a run needing at least as much memory as its heaviest point
    worked, 'oom' when a run needing no more than its lightest point ran out, else None. A success wins over a failure: the
    edge moves with what the desktop holds, so one OOM does not condemn a point that worked."""
    heavy, light = memPoint(params, depth, max(bs)), memPoint(params, depth, min(bs))
    oom = False
    for r in records:
        if r.get("model") != model or r["outcome"] not in ("ok", "oom"):
            continue
        if r["outcome"] == "ok" and needsAtLeast(recPoint(r), heavy):
            return "ok"
        if r["outcome"] == "oom" and needsAtLeast(light, recPoint(r)):
            oom = True
    return "oom" if oom else None


# Outliers: points whose result disagrees with what else is known, flagged for a retry (bounded, so auto always ends).
OUTLIER_TOLERANCE = 0.15
NEIGHBOUR_AXES = ["nCpuMoe", "ctx"]  # axes along which decode should move one way; threads and ubatch have interior optima


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def outliers(records, model):
    """{(paramsKey, depth, B): {"kind", "reason", "retry"}} for this model's records.
      contradiction: ran out of memory although a configuration needing at least as much memory worked (a flaky edge, or
                     something else held the GPU); retried until three runs of that configuration exist.
      repeats:       runs of the same point differ by more than 15% from their median; retried until three runs exist.
      neighbour:     decode speed more than 15% below or above both neighbours along one axis, all else equal; retried once."""
    recs = [r for r in effective(records, model) if r.get("model") == model and r["outcome"] in ("ok", "oom")]
    runs = {}
    for r in recs:
        runs.setdefault(paramsKey(r["params"]), set()).add(r["ts"])
    flags = {}
    oks = [r for r in recs if r["outcome"] == "ok"]
    for r in recs:
        if r["outcome"] == "oom" and any(needsAtLeast(recPoint(o), recPoint(r)) for o in oks):
            pk = paramsKey(r["params"])
            flags[(pk, r["depth"], r["B"])] = {"kind": "contradiction", "retry": len(runs[pk]) < 3,
                                               "reason": "ran out of memory, but a configuration needing at least as much memory worked"}
    groups, params = {}, {}
    for r in oks:
        if r.get("tgTps"):
            key = (paramsKey(r["params"]), r["depth"], r["B"])
            groups.setdefault(key, []).append(r["tgTps"])
            params[key] = r["params"]
    value = {}
    for key, vals in groups.items():
        med = _median(vals)
        value[key] = med
        dev = max(abs(v - med) / med for v in vals) if med else 0
        if len(vals) >= 2 and dev > OUTLIER_TOLERANCE:
            flags[key] = {"kind": "repeats", "retry": len(vals) < 3,
                          "reason": "%d runs differ by up to %d%% from their median (%.1f tok/s)" % (len(vals), round(dev * 100), med)}
    for axis in NEIGHBOUR_AXES:
        lines = {}
        for key in value:
            p = dict(params[key])
            pos = p.pop(axis, None)
            if isinstance(pos, (int, float)):
                lines.setdefault((json.dumps(p, sort_keys=True), key[1], key[2]), []).append((pos, key))
        for pts in lines.values():
            pts.sort()
            for (_, lo), (x, key), (_, hi) in zip(pts, pts[1:], pts[2:]):
                v, a, b = value[key], value[lo], value[hi]
                if key in flags or lo in flags or hi in flags:  # a flagged neighbour is no yardstick
                    continue
                if v < (1 - OUTLIER_TOLERANCE) * min(a, b) or v > (1 + OUTLIER_TOLERANCE) * max(a, b):
                    flags[key] = {"kind": "neighbour", "retry": len(groups[key]) < 2,
                                  "reason": "decode %.1f tok/s against %.1f and %.1f at the neighbouring %s values" % (v, a, b, axis)}
    return flags


def viewPoints(cfg, spec):
    """Every (params, depth, Bs) the view covers."""
    base = {k: cfg.get(k) for k in config.PARAM_KEYS}
    base.update({k: v for k, v in spec.get("fixed", {}).items() if k in config.PARAM_KEYS})
    axes = spec.get("axes", {})
    names = list(axes)
    for combo in itertools.product(*[axes[n] for n in names]):
        params = dict(base)
        bs, depths = list(spec.get("B", [1])), list(spec.get("depth", [2048]))
        for n, v in zip(names, combo):
            if n == "B":
                bs = [v]
            elif n == "depth":
                depths = [v]
            else:
                params[n] = v
        for depth in depths:
            yield params, int(depth), [int(b) for b in bs]


def plan(cfg, spec, records=None):
    """The view's work. spec: {"axes": {name: [values]} (PARAM_KEYS, "B" or "depth"), "fixed": {param: value}, "B": [..],
    "depth": [..], "ntg": n}. Returns {"todo": gaps [{params, depth, B, predicted}], "inferred": gaps that must run out of
    memory, "retry": outliers to re-measure [{params, depth, B, kind, reason}], "flagged": outliers already retried enough}."""
    records = scopedHistory(cfg, history() if records is None else records, int(spec.get("ntg", 128)))
    path, rid = registry.resolve(cfg)
    model = rid or os.path.basename(path)
    be = backends.get(cfg)
    ntg = int(spec.get("ntg", 128))
    known = {(paramsKey(r["params"]), r["depth"], r["B"]) for r in records if r.get("model") == model}
    flags = outliers(records, model)
    trusted = effective(records, model)
    measuredOk = {(paramsKey(r["params"]), r["depth"], r["B"]) for r in trusted if r.get("model") == model and r["outcome"] == "ok"}
    out = {"todo": [], "inferred": [], "probe": [], "retry": [], "flagged": []}
    merged = {}  # (paramsKey, depth) -> (params, set of B): with B as an axis, one configuration appears once per B value
    layers = registry.facts(cfg).get("expertLayers") or registry.facts(cfg).get("blockCount")
    for params, depth, bs in viewPoints(cfg, spec):
        if layers and (params.get("nCpuMoe") or 0) > layers:  # every expert layer is on the CPU at nCpuMoe = layers already
            continue
        merged.setdefault((paramsKey(params), depth), (params, set()))[1].update(bs)
    inferredCells = []
    for (pk, depth), (params, bset) in merged.items():
        bs = sorted(bset)
        run = dict(cfg, **params)
        fits = [b for b in bs if be.fitsBench(run, depth, ntg, b)]
        miss = sorted({b for b in fits if (pk, depth, b) not in known})
        byPred = {}  # each B predicted on its own: one heavy B must not decide the light ones
        for b in miss:
            byPred.setdefault(predict(params, depth, [b], model, trusted), []).append(b)
        for pred, blist in byPred.items():
            g = {"params": params, "depth": depth, "B": blist, "predicted": pred}
            out["inferred" if pred == "oom" else "todo"].append(g)
            if pred == "oom":
                inferredCells += [(params, depth, b) for b in blist]
        bad = {}
        for b in fits:
            f = flags.get((pk, depth, b))
            if f:
                bad.setdefault((f["kind"], f["reason"], f["retry"]), []).append(b)
        for (kind, reason, retry), blist in bad.items():
            out["retry" if retry else "flagged"].append({"params": params, "depth": depth, "B": sorted(blist), "kind": kind, "reason": reason})
    if spec.get("probeEdges", True):
        out["probe"] = edgeProbes(spec, inferredCells, measuredOk)
    return out


def edgeProbes(spec, cells, measuredOk):
    """Inferred-OOM cells one step (along a view axis, B or depth) from a cell that measurably worked: running them proves where
    the edge is. A probe that fails becomes a measured failure and stops the walk; one that works makes the next cell a probe."""
    axes = dict(spec.get("axes", {}))
    if "B" not in axes:
        axes["B"] = list(spec.get("B", [1]))
    if "depth" not in axes:
        axes["depth"] = list(spec.get("depth", [2048]))
    order = {a: sorted({float(v) for v in vals}) for a, vals in axes.items()}
    groups = {}
    for params, depth, b in cells:
        nbrs = []
        for a, vals in order.items():
            cur = float(b if a == "B" else depth if a == "depth" else params.get(a) or 0)
            if cur not in vals:
                continue
            i = vals.index(cur)
            for j in (i - 1, i + 1):
                if 0 <= j < len(vals):
                    p2, d2, b2 = dict(params), depth, b
                    if a == "B":
                        b2 = int(vals[j])
                    elif a == "depth":
                        d2 = int(vals[j])
                    else:
                        p2[a] = type(params.get(a) or 0)(vals[j])
                    nbrs.append((paramsKey(p2), d2, b2))
        if any(n in measuredOk for n in nbrs):
            groups.setdefault((paramsKey(params), depth), (params, []))[1].append(b)
    return [{"params": p, "depth": d, "B": sorted(bl), "kind": "edge", "reason": "inferred to run out of memory beside a configuration that worked: run to prove the edge"}
            for (_, d), (p, bl) in groups.items()]


def pickNext(todo):
    """Unknown feasibility first, choosing the point whose outcome settles the most others (bisection on the memory edge); then
    points predicted to fit, lightest first."""
    unknown = [g for g in todo if g["predicted"] is None]
    if unknown:
        def score(g):
            gp = memPoint(g["params"], g["depth"], max(g["B"]))
            pts = [memPoint(h["params"], h["depth"], max(h["B"])) for h in unknown if h is not g]
            more = sum(1 for hp in pts if needsAtLeast(hp, gp))
            less = sum(1 for hp in pts if needsAtLeast(gp, hp))
            return (min(more, less), more + less)
        return max(unknown, key=score)
    return min(todo, key=lambda g: (-(g["params"].get("nCpuMoe") or 0), g["params"].get("ctx") or 0, g["depth"]))


def auto(cfg, spec, log=None, progress=None, stop=None, say=print):
    """Fill the view one run at a time, re-planning after each: contradictions first (they mislead the inference), then gaps,
    then the other outliers. Ends when nothing is left, after maxRuns, or when `stop` is set."""
    limit = int(spec.get("maxRuns", 200))
    ntg = int(spec.get("ntg", 128))
    done = 0
    while done < limit and not (stop and stop.is_set()):
        p = plan(cfg, spec)
        contra = [g for g in p["retry"] if g["kind"] == "contradiction"]
        if contra:
            g, why = contra[0], "retry (%s)" % contra[0]["reason"]
        elif p["todo"]:
            g, why = pickNext(p["todo"]), "gap"
        elif p["probe"]:
            g, why = min(p["probe"], key=lambda h: (-(h["params"].get("nCpuMoe") or 0), h["params"].get("ctx") or 0, h["depth"], min(h["B"]))), "edge probe"
        elif p["retry"]:
            g, why = p["retry"][0], "retry (%s)" % p["retry"][0]["reason"]
        else:
            say("auto: nothing left (%d inferred to run out of memory, %d outliers already retried)" % (len(p["inferred"]), len(p["flagged"])))
            break
        label = " ".join("%s=%s" % (k, g["params"][k]) for k in spec.get("axes", {}) if k in g["params"]) + " depth=%d B=%s" % (g["depth"], ",".join(map(str, g["B"])))
        if progress:
            progress(done, done + len(p["todo"]) + len(p["probe"]) + len(p["retry"]), "auto %s: %s (%d gaps, %d edge probes, %d retries, %d inferred OOM)" % (why, label, len(p["todo"]), len(p["probe"]), len(p["retry"]), len(p["inferred"])))
        changed = {k: v for k, v in g["params"].items() if cfg.get(k) != v}
        note = spec.get("note", "auto") + ("" if why == "gap" else "; " + why)
        for r in point(cfg, changed, g["depth"], ntg, g["B"], log=log, note=note):
            say("auto %s: %s B=%d %s tg=%s pp=%s peak=%sMiB" % (why, label, r["B"], r["outcome"], r.get("tgTps", "-"), r.get("ppTps", "-"), r.get("peakVramMiB")))
        done += 1
    return done

