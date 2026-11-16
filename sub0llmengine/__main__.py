"""Sub0LlmEngine command line.

  python -m sub0llmengine config                 the effective configuration and the server command it makes
  python -m sub0llmengine start | stop | status  the engine server (OpenAI-compatible API)
  python -m sub0llmengine machine                this machine's id and facts
  python -m sub0llmengine sweep --ncmoe 30,32 --ctx 65536,131072 --depth 2048,8192 --B 1,4,8
                                                 bench every combination; every point (failures too) goes to bench/<machine>.jsonl
  python -m sub0llmengine serve [--port 8781]    the tuning page: heatmaps over the history, pick a configuration, queue sweeps

Common option: --config FILE (a config layer on top of config/engine.defaults.json and engine.local.json).
"""
import argparse
import json
import os
import sys

from . import bench, config, machine, process, tuneserver


def csv(s, conv=int):
    return [conv(x) for x in str(s).split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sub0llmengine", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="extra config layer (saved changes go here)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config")
    sub.add_parser("machine")
    st = sub.add_parser("start")
    st.add_argument("--no-wait", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("status")
    sw = sub.add_parser("sweep")
    for flag, key, conv in [("--ncmoe", "nCpuMoe", int), ("--ctx", "ctx", int), ("--ub", "ubatch", int), ("--batch", "batch", int),
                            ("--threads", "threads", int), ("--ctk", "cacheTypeK", str), ("--ctv", "cacheTypeV", str)]:
        sw.add_argument(flag, dest=key)
    sw.add_argument("--depth", default="2048", help="tokens already in each sequence's context (comma list)")
    sw.add_argument("--ntg", type=int, default=128, help="tokens generated per sequence")
    sw.add_argument("--B", default="1,4,8", help="concurrent sequences (comma list)")
    sw.add_argument("--note", default="")
    sw.add_argument("--again", action="store_true", help="re-measure points already in the history")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8781)
    a = ap.parse_args(argv)
    if a.config:
        config.addLayer(a.config)
    cfg = config.load()

    if a.cmd == "config":
        print(json.dumps(cfg, indent=2))
        print(" ".join(process.command(cfg)))
    elif a.cmd == "machine":
        print(json.dumps(machine.info(), indent=2))
    elif a.cmd == "start":
        return process.start(cfg, wait=not a.no_wait)
    elif a.cmd == "stop":
        return process.stop(cfg)
    elif a.cmd == "status":
        return process.status(cfg)
    elif a.cmd == "sweep":
        if process.running(cfg):
            raise SystemExit("the engine is running at %s: stop it first (a bench needs the GPU)" % process.url(cfg))
        grid = {"depth": csv(a.depth), "ntg": a.ntg, "B": csv(a.B), "note": a.note}
        for key, conv in [("nCpuMoe", int), ("ctx", int), ("ubatch", int), ("batch", int), ("threads", int), ("cacheTypeK", str), ("cacheTypeV", str)]:
            val = getattr(a, key)
            if val:
                grid[key] = csv(val, conv)
        bench.sweep(cfg, grid, log=os.path.join(config.STATE_DIR, "sweep.log"), again=a.again, say=lambda m: print(m, flush=True))
    elif a.cmd == "serve":
        tuneserver.serve(a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
