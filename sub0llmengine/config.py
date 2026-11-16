"""Layered configuration: config/engine.defaults.json < engine.local.json < $SUB0LLMENGINE_CONFIG < --config FILE.

Keys starting with "_" are comments. engine.local.json is gitignored: it holds this machine's choice (binary folder, model,
placement, context, slots). A consumer such as Sub0Squad can keep its own file and pass it with --config.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = os.path.join(ROOT, "config", "engine.defaults.json")
LOCAL = os.path.join(ROOT, "engine.local.json")
BENCH_DIR = os.path.join(ROOT, "bench")
WEB_DIR = os.path.join(ROOT, "web")
STATE_DIR = os.path.join(ROOT, "out")
IS_WINDOWS = os.name == "nt"

# The knobs one configuration is made of (placement, memory, compute), in the order the tuning page shows them. Bench-only axes
# are "B" (concurrent sequences; the server's slots) and "depth" (tokens already in each sequence's context when it decodes).
PARAM_KEYS = ["nCpuMoe", "ctx", "ubatch", "batch", "threads", "cacheTypeK", "cacheTypeV", "flashAttn", "kvUnified", "mmap", "gpuLayers"]

_extra = []


def loadJson(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def strip(d):
    return {k: v for k, v in (d or {}).items() if not k.startswith("_")}


def addLayer(path):
    """Add a config file on top of the others (the --config option)."""
    _extra.append(os.path.abspath(path))


def layers():
    out = [DEFAULTS, LOCAL]
    env = os.environ.get("SUB0LLMENGINE_CONFIG")
    if env:
        out.append(env)
    return out + _extra


def load():
    cfg = {}
    for p in layers():
        cfg.update(strip(loadJson(p, {})))
    return cfg


def writableLayer():
    """The file changes are saved to: the top --config/env layer when given, else engine.local.json."""
    return layers()[-1] if len(layers()) > 2 else LOCAL


def save(updates):
    path = writableLayer()
    cur = loadJson(path, {})
    cur.update(updates)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cur, f, indent=2)
        f.write("\n")
    return path, cur
