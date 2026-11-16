"""Bounded experiments for requested workload regions, including unmeasured regions."""
import math
import os

from . import backends, bench, config, machine, registry


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("%s must be an integer in %d..%d" % (name, low, high))
    return value


def validate(spec):
    if not isinstance(spec, dict):
        raise ValueError("exploration must be an object")
    for key, high in (("depths", 2**30), ("concurrencies", 1024)):
        values = spec.get(key)
        if not isinstance(values, list) or not 1 <= len(values) <= 16:
            raise ValueError("%s must contain 1..16 values" % key)
        for value in values:
            integer(value, key, 1, high)
    integer(spec.get("ntg", 128), "generated tokens", 1, 1048576)
    integer(spec.get("maxContext", 1048576), "allocation ceiling", 256, 2**30)
    integer(spec.get("minSlotContext", 16384), "minimum context per slot", 256, 2**30)
    integer(spec.get("minPasses", 2), "minimum passes", 1, 5)
    integer(spec.get("maxRuns", 8), "run budget", 1, 64)
    integer(spec.get("timeoutSeconds", 900), "timeout per run", 10, 86400)
    if not isinstance(spec.get("fixed", {}), dict) or set(spec.get("fixed", {})) - set(config.PARAM_KEYS):
        raise ValueError("unknown baseline knob")


def plan(cfg, spec, records=None):
    validate(spec)
    be = backends.get(cfg)
    if be.name != "llamacpp":
        raise ValueError("This engine needs its own workload-allocation contract before exploration is available.")
    path, rid = registry.resolve(cfg)
    identity = dict(machine=machine.info()["id"], backend=be.name, model=rid or os.path.basename(path), build=be.buildLabel(cfg))
    if spec.get("identity") and spec["identity"] != identity:
        raise ValueError("Selected cohort differs from this host's configured model/backend/build. Select its current cohort first.")
    records = bench.history() if records is None else records
    ntg, passes = spec.get("ntg", 128), spec.get("minPasses", 2)
    records = [r for r in records if not r.get("excluded") and r.get("ntg") == ntg and all(r.get(k) == v for k, v in identity.items())]
    base = {k: cfg.get(k) for k in be.selectionParams()}
    base.update(spec.get("fixed", {}))
    cells = []
    for depth in sorted(set(spec["depths"])):
        for b in sorted(set(spec["concurrencies"])):
            params = dict(base)
            # Per-sequence rounding is conservative for unified and separate KV allocation.
            minimum = spec.get("minSlotContext", 16384)
            required = b * math.ceil(max(depth + ntg, minimum) / 256) * 256
            params["ctx"] = max(base["ctx"], required)
            cell = dict(depth=depth, B=b, params=params, requiredContext=required, passes=0, attempts=0, speed=None)
            if depth + ntg < minimum:
                cells.append(dict(cell, state="policy", reason="prompt + output falls below your minimum slot window; include the slot boundary", pending=False))
                continue
            if params["ctx"] > spec.get("maxContext", 1048576):
                cells.append(dict(cell, state="budget", reason="exceeds your total allocation ceiling", pending=False))
                continue
            matches = [r for r in records if r.get("params") == params and r.get("depth") == depth and r.get("B") == b]
            ok = [r for r in matches if r.get("outcome") == "ok" and isinstance(r.get("tgTps"), (int, float)) and math.isfinite(r["tgTps"]) and r["tgTps"] > 0]
            failures = [r for r in matches if r not in ok]
            cell.update(passes=len(ok), attempts=len(matches), speed=bench._median([r["tgTps"] / b for r in ok]) if ok else None)
            if failures:
                state = "mixed" if ok else ("oom" if any(r.get("outcome") == "oom" for r in failures) else "error")
                pending = bool(spec.get("verifyFailures")) and len(matches) < max(3, passes + 1)
                reason = "observed failures; bounded verification enabled" if pending else "observed failures; enable verification to retry"
            elif len(ok) >= passes:
                state, pending, reason = "measured", False, "requested repeats collected"
            elif ok:
                state, pending, reason = "thin", True, "more repeats requested"
            else:
                inferred = bench.predict(params, depth, [b], identity["model"], records)
                state = "inferred" if inferred == "oom" else "unknown"
                pending = state != "inferred" or bool(spec.get("verifyFailures"))
                reason = "memory hypothesis, not a measured failure" if state == "inferred" else "no exact workload measurement"
            cells.append(dict(cell, state=state, pending=pending, reason=reason))
    return dict(identity=identity, cells=cells, pending=sum(c["pending"] for c in cells),
                missingPasses=sum(max(1, passes-c["passes"]) for c in cells if c["pending"]),
                ntg=ntg, minPasses=passes, maxRuns=spec.get("maxRuns", 8),
                caveat="Allocation ceiling is your experiment budget, not a model limit. Extended-context quality is not validated by this throughput benchmark.")


def run(cfg, spec, log=None, progress=None, stop=None):
    validate(spec)
    done = 0
    while done < spec.get("maxRuns", 8) and not (stop and stop.is_set()):
        plan_now = plan(cfg, spec)
        pending = [c for c in plan_now["cells"] if c["pending"]]
        if not pending:
            break
        # Collect unknown points before repeating, then lighter workloads first.
        cell = min(pending, key=lambda c: (c["attempts"], c["depth"] * c["B"]))
        if progress:
            progress(done, spec.get("maxRuns", 8), "explore depth=%d B=%d ctx=%d (%s)" % (cell["depth"], cell["B"], cell["params"]["ctx"], cell["state"]))
        bench.point(cfg, cell["params"], cell["depth"], plan_now["ntg"], [cell["B"]], log=log,
                    note="requested envelope; " + cell["reason"], timeout=spec.get("timeoutSeconds", 900))
        done += 1
    return done
