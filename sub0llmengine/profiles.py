"""Named profiles: config layers in config/profiles/<name>.json that carry the evidence they were chosen from.

A profile is an ordinary config layer (applied with --profile NAME, the same as --config FILE) plus "_evidence":
{build, model, records: [bench timestamps], workload, measured, note}. `check` compares that evidence with what the
profile would start now (the build label of its binDir, the registry id of its model, the records still in this
machine's history) so a profile chosen on another build or model is flagged stale instead of trusted.
"""
import os

from . import backends, bench, config, registry

DIR = os.path.join(config.ROOT, "config", "profiles")


def path(name):
    p = os.path.join(DIR, name + ".json")
    if not os.path.isfile(p):
        raise SystemExit("no profile '%s' (have: %s)" % (name, ", ".join(names()) or "none"))
    return p


def names():
    return sorted(f[:-5] for f in os.listdir(DIR) if f.endswith(".json")) if os.path.isdir(DIR) else []


def load(name):
    return config.loadJson(path(name), {})


def check(name, base=None, history=None):
    """{name, comment, settings, evidence, current: {build, model}, problems: [...], stale: bool}."""
    raw = load(name)
    cfg = dict(base if base is not None else config.load(), **config.strip(raw))
    ev = raw.get("_evidence") or {}
    problems = []
    try:
        _, rid = registry.resolve(cfg)
    except SystemExit as e:
        rid, problems = None, problems + ["model does not resolve: %s" % e]
    try:
        build = backends.get(cfg).buildLabel(cfg)
    except SystemExit as e:
        build, problems = None, problems + [str(e)]
    if not ev:
        problems.append("no _evidence recorded")
    else:
        if ev.get("build") and build and ev["build"] != build:
            problems.append("chosen on %s, would start %s" % (ev["build"], build))
        if ev.get("model") and rid and ev["model"] != rid:
            problems.append("chosen for %s, would start %s" % (ev["model"], rid))
        if ev.get("records"):
            have = {r.get("ts") for r in (history if history is not None else bench.history())}
            missing = [t for t in ev["records"] if t not in have]
            if missing:
                problems.append("evidence records not in this machine's history: %s" % ", ".join(missing))
    keys = list(backends.get(cfg).selectionParams()) + ["model", "slots", "squadCtx", "kvUnifiedPerSlot"]
    return {"name": name, "comment": raw.get("_comment", ""), "settings": {k: cfg.get(k) for k in keys if k in cfg},
            "evidence": ev, "current": {"build": build, "model": rid}, "problems": problems, "stale": bool(problems)}
