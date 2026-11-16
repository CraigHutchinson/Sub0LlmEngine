"""Sub0LlmEngine command line.

  python -m sub0llmengine config [--json]        the effective configuration and the server command it makes
  python -m sub0llmengine start | stop | status [--json]
                                                 the engine server (OpenAI-compatible API); --json prints what a client
                                                 needs (sub0llmengine.engine.v1): endpoint, slots, context per slot,
                                                 model id and path, build, and whether it matches the configuration
  python -m sub0llmengine model [REF]            resolve a model (alias, registry id or file): id, path, registry facts
  python -m sub0llmengine machine                this machine's id and facts
  python -m sub0llmengine sweep --ncmoe 30,32 --ctx 65536,131072 --depth 2048,8192 --B 1,4,8
                                                 bench every combination; every point (failures too) goes to bench/<machine>.jsonl
  python -m sub0llmengine auto --x ctx=32768,65536,131072 --y nCpuMoe=30,32,34,36,40 --B 1,4,8 --depth 2048 [--plan]
                                                 fill the gaps of that view: skips points that must run out of memory,
                                                 measures first what settles the most others, re-plans after each run
  python -m sub0llmengine exclude --since 2026-11-16T12:00 --until 2026-11-16T12:35 --reason "GPU shared with another bench"
                                                 keep records but leave them out of views and plans (they become gaps again)
  python -m sub0llmengine axes [--out FILE]      the runtime axes and knobs, simplified (JSON; also /api/axes)
  python -m sub0llmengine spike [--only 0,2] [--tokens 16384]
                                                 change configuration mid-job: save a slot's KV, restart with other knobs,
                                                 restore it, and check the output; appends to out/spike/reconfigure.jsonl
  python -m sub0llmengine serve [--port 8781]    the tuning page: heatmaps over the history, pick a configuration, queue sweeps

Common option: --config FILE (a config layer on top of config/engine.defaults.json and engine.local.json).
"""
import argparse
import json
import os
import sys

from . import axes, backends, bench, config, machine, process, registry, selection, spike, tuneserver


def csv(s, conv=int):
    return [conv(x) for x in str(s).split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sub0llmengine", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config layer (saved changes go here)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cf = sub.add_parser("config")
    cf.add_argument("--json", action="store_true", help="one JSON document: configuration, layers, model, build, command")
    md = sub.add_parser("model")
    md.add_argument("ref", nargs="?", help="alias, registry id or file path (default: the configured model)")
    sub.add_parser("machine")
    sl = sub.add_parser("selection", help="validate a tuning-map export against local history; never starts an engine")
    sl.add_argument("file")
    sl.add_argument("--out", help="write a new config layer (refuses to overwrite); active settings stay unchanged")
    st = sub.add_parser("start")
    st.add_argument("--no-wait", action="store_true")
    st.add_argument("--json", action="store_true", help="progress to stderr, then the engine description as JSON on stdout")
    sub.add_parser("stop")
    ss = sub.add_parser("status")
    ss.add_argument("--json", action="store_true", help="the engine description as JSON (exit code 1 when not answering)")
    sw = sub.add_parser("sweep")
    for flag, key, conv in [("--ncmoe", "nCpuMoe", int), ("--ctx", "ctx", int), ("--ub", "ubatch", int), ("--batch", "batch", int),
                            ("--threads", "threads", int), ("--ctk", "cacheTypeK", str), ("--ctv", "cacheTypeV", str)]:
        sw.add_argument(flag, dest=key)
    sw.add_argument("--depth", default="2048", help="tokens already in each sequence's context (comma list)")
    sw.add_argument("--ntg", type=int, default=128, help="tokens generated per sequence")
    sw.add_argument("--B", default="1,4,8", help="concurrent sequences (comma list)")
    sw.add_argument("--note", default="")
    sw.add_argument("--again", action="store_true", help="re-measure points already in the history")
    au = sub.add_parser("auto")
    au.add_argument("--x", required=True, help="AXIS=v1,v2,... (a config key such as ctx or nCpuMoe, or B, or depth)")
    au.add_argument("--y", required=True, help="AXIS=v1,v2,...")
    au.add_argument("--fix", action="append", default=[], help="KEY=VALUE held fixed (repeatable); other keys come from the config")
    au.add_argument("--B", default="1,4,8")
    au.add_argument("--depth", default="2048")
    au.add_argument("--ntg", type=int, default=128)
    au.add_argument("--max-runs", type=int, default=200)
    au.add_argument("--plan", action="store_true", help="only show what would run")
    ex = sub.add_parser("exclude")
    ex.add_argument("--since", required=True)
    ex.add_argument("--until", required=True)
    ex.add_argument("--reason", required=True)
    ex.add_argument("--note", help="only records with exactly this note")
    ax = sub.add_parser("axes")
    ax.add_argument("--out", help="write the definition to this file")
    sp = sub.add_parser("spike")
    sp.add_argument("--only", help="comma list of transition numbers (default: all)")
    sp.add_argument("--tokens", type=int, default=16384, help="prompt tokens prefilled before the switch")
    sp.add_argument("--list", action="store_true", help="show the transitions and what each changes")
    sp.add_argument("--model", help="registry model id or alias for this run (default: the config's)")
    sp.add_argument("--set", action="append", default=[], help="KEY=VALUE base config override for this run (repeatable), e.g. gpuLayers=40")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8781)
    a = ap.parse_args(argv)
    if a.config:
        config.addLayer(a.config)
    cfg = config.load()

    if a.cmd == "config":
        if a.json:
            print(json.dumps({"config": cfg, "layers": [x for x in config.layers() if os.path.exists(x)], "writableLayer": config.writableLayer(),
                              "model": process.model(cfg), "build": backends.get(cfg).buildLabel(cfg), "command": process.command(cfg)}, indent=2))
        else:
            print(json.dumps(cfg, indent=2))
            print(" ".join(process.command(cfg)))
    elif a.cmd == "model":
        print(json.dumps(process.model(cfg, a.ref), indent=2))
    elif a.cmd == "machine":
        print(json.dumps(machine.info(), indent=2))
    elif a.cmd == "selection":
        try:
            profile = config.loadJson(a.file)
            proposed = profile.get("engineConfig", {}) if isinstance(profile, dict) else {}
            candidate = dict(cfg, **proposed)
            result = selection.validate(profile, bench.history(), machine.info()["id"], backends.get(candidate).buildLabel(candidate))
            # Resolve the exported model id and the real server path before emitting a usable layer.
            registry.resolve(candidate)
            result["command"] = process.command(candidate)
            if a.out:
                with open(a.out, "x", encoding="utf-8") as f:
                    json.dump(result["engineConfig"], f, indent=2)
                    f.write("\n")
                result["configFile"] = os.path.abspath(a.out)
            print(json.dumps(result, indent=2))
        except (ValueError, OSError, TypeError) as e:
            raise SystemExit("selection: " + str(e)) from e
    elif a.cmd == "start":
        if not a.json:
            return process.start(cfg, wait=not a.no_wait)
        rc = process.start(cfg, wait=not a.no_wait, say=process.err)
        print(json.dumps(process.info(cfg), indent=2))
        return rc
    elif a.cmd == "stop":
        return process.stop(cfg)
    elif a.cmd == "status":
        if not a.json:
            return process.status(cfg)
        d = process.info(cfg)
        print(json.dumps(d, indent=2))
        return 0 if d["running"] else 1
    elif a.cmd == "sweep":
        if process.running(cfg):
            raise SystemExit("the engine is running at %s: stop it first (a bench needs the GPU)" % process.url(cfg))
        grid = {"depth": csv(a.depth), "ntg": a.ntg, "B": csv(a.B), "note": a.note}
        for key, conv in [("nCpuMoe", int), ("ctx", int), ("ubatch", int), ("batch", int), ("threads", int), ("cacheTypeK", str), ("cacheTypeV", str)]:
            val = getattr(a, key)
            if val:
                grid[key] = csv(val, conv)
        bench.sweep(cfg, grid, log=os.path.join(config.STATE_DIR, "sweep.log"), again=a.again, say=lambda m: print(m, flush=True))
    elif a.cmd == "auto":
        def num(v):
            try:
                return int(v)
            except ValueError:
                return v
        grid = {}
        for spec in (a.x, a.y):
            k, _, vals = spec.partition("=")
            grid[k] = [num(v) for v in vals.split(",") if v]
        fixed = {k: num(v) for k, _, v in (f.partition("=") for f in a.fix)}
        spec = {"axes": grid, "fixed": fixed, "B": csv(a.B), "depth": csv(a.depth), "ntg": a.ntg, "maxRuns": a.max_runs}
        p = bench.plan(cfg, spec)
        print("%d gap(s), %d outlier(s) to retry, %d inferred to run out of memory, %d outlier(s) already retried" % (len(p["todo"]), len(p["retry"]), len(p["inferred"]), len(p["flagged"])))
        if a.plan:
            pick = lambda g: {k: g["params"][k] for k in grid if k in g["params"]}
            for g in p["todo"]:
                print("  gap    ", pick(g), "depth", g["depth"], "B", g["B"], "predicted", g["predicted"])
            for g in p["retry"]:
                print("  retry  ", pick(g), "depth", g["depth"], "B", g["B"], g["kind"] + ":", g["reason"])
            for g in p["flagged"]:
                print("  flagged", pick(g), "depth", g["depth"], "B", g["B"], g["kind"] + ":", g["reason"])
            for g in p["inferred"]:
                print("  oom?   ", pick(g), "depth", g["depth"])
            return 0
        if process.running(cfg):
            raise SystemExit("the engine is running at %s: stop it first (a bench needs the GPU)" % process.url(cfg))
        bench.auto(cfg, spec, log=os.path.join(config.STATE_DIR, "sweep.log"), say=lambda m: print(m, flush=True))
    elif a.cmd == "exclude":
        print("excluded %d record(s)" % bench.exclude(a.since, a.until, a.reason, a.note))
    elif a.cmd == "axes":
        text = json.dumps(axes.describe(cfg), indent=2)
        if a.out:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        print(text)
    elif a.cmd == "spike":
        if a.model:
            cfg = dict(cfg, model=a.model)
        for kv in a.set:
            k, _, v = kv.partition("=")
            cfg[k] = int(v) if v.lstrip("-").isdigit() else v
        knobs = [k for k in backends.get(cfg).knobs() if k["change"] == "load"]
        if a.list:
            for i, (name, x, y) in enumerate(spike.transitions(cfg)):
                print(i, name, json.dumps(axes.diff(knobs, dict(cfg, **x), dict(cfg, **y))))
            return 0
        if process.running(cfg):
            raise SystemExit("the engine is running at %s: stop it first (the spike needs the GPU)" % process.url(cfg))
        spike.run(cfg, csv(a.only) if a.only else None, n=a.tokens, say=lambda m: print(m, flush=True))
    elif a.cmd == "serve":
        tuneserver.serve(a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
