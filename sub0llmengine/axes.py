"""The runtime axes and the knobs that move them: one simplified, backend-neutral definition.

The tuning page, the CLI and the spike experiments read this instead of hard-coding llama.cpp flags.

  axes      what a user trades: speed, context, concurrency, prefill (each with its metric and the knobs that move it)
  workload  what a bench or a request varies: depth, B, ntg
  knobs     the backend's settings: type, range, unit, when they can change ("load" needs a restart, "request" does not),
            and, once measured, whether a sequence's KV survives a change of that knob (`transfer`)
  transfer  how the backend moves a sequence's KV between configurations, and what the spike measured about it

`python -m sub0llmengine axes` prints it; the tuning server serves it at /api/axes.
"""
import json
import os

from . import backends, config, registry

FORMAT = "sub0llmengine.axes.v1"
SPIKE_DIR = os.path.join(config.STATE_DIR, "spike")
SPIKE_RESULTS = os.path.join(SPIKE_DIR, "reconfigure.jsonl")

AXES = [
    dict(id="speed", label="Speed", unit="tok/s per sequence", metric="tgTps / B", better="higher",
         alternatives={"requestRate": "requests per minute: 60 / (B*depth/ppTps + ntg*B/tgTps)"}),
    dict(id="context", label="Context", unit="tokens per sequence", metric="depth", better="higher",
         note="the tested prompt depth; allocated context (ctx) is a knob, not evidence"),
    dict(id="concurrency", label="Concurrency", unit="sequences", metric="B", better="higher"),
    dict(id="prefill", label="Prefill", unit="tok/s", metric="ppTps", better="higher"),
]
WORKLOAD = [
    dict(id="depth", label="prompt depth per sequence", unit="tokens"),
    dict(id="B", label="concurrent sequences", unit="sequences", servedBy="slots"),
    dict(id="ntg", label="tokens generated per sequence", unit="tokens"),
]


def spikeResults(path=SPIKE_RESULTS):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def transferFindings(results, model=None, byBuild=False):
    """Per knob, for one model: 'kept' when a change of it restored the KV, reused it (only the follow-up was computed) and
    gave identical output; 'restored-not-reused' when the KV restored and matched but the server re-processed the prefix
    anyway; 'lost' when the restore failed or the output differed. Absent: unmeasured. Within one build the worst verdict
    wins; across builds the newest build that measured a knob wins (a server upgrade can change the answer).
    byBuild=True returns {build: {knob: verdict}} instead."""
    rank = {"lost": 3, "restored-not-reused": 2, "kept": 1}
    builds, newest = {}, {}
    for r in results:
        if model and r.get("model") != model:
            continue
        changed = set(r.get("changed", {}))
        if r.get("inconclusive"):  # e.g. a model that is not deterministic run-to-run: no verdict either way
            continue
        if not changed or r.get("restored") is None or (r.get("restored") and r.get("identical") is None and not r.get("transferFaithful")):
            continue
        faithful = r.get("identical") or r.get("transferFaithful")  # the control showed the restored KV equals KV computed in B
        verdict = ("kept" if r.get("reused", True) else "restored-not-reused") if r.get("restored") and faithful else "lost"
        b = r.get("build") or "unknown"
        out = builds.setdefault(b, {})
        newest[b] = max(newest.get(b, ""), r.get("time") or "")
        for k in changed:
            if rank[verdict] > rank.get(out.get(k), 0):
                out[k] = verdict
    if byBuild:
        return builds
    found = {}
    for b in sorted(builds, key=lambda b: newest[b]):  # older first, newer overwrite
        found.update(builds[b])
    return found


def describe(cfg=None):
    cfg = cfg if cfg is not None else config.load()
    be = backends.get(cfg)
    knobs = be.knobs()
    facts = {}
    try:
        facts = registry.facts(cfg) or {}
    except (SystemExit, Exception):
        pass
    found = transferFindings(spikeResults(), cfg.get("model"))
    for k in knobs:
        if k.get("maxFact") and facts.get(k["maxFact"]):
            k["max"] = facts[k["maxFact"]]
        if k["id"] in cfg:
            k["current"] = cfg[k["id"]]
        if k["change"] == "load":
            k["transfer"] = found.get(k["id"], "unmeasured")
    axes = []
    for a in AXES:
        axes.append(dict(a, drivenBy=[k["id"] for k in knobs if a["id"] in k.get("affects", [])]))
    transfer = be.contextTransfer()
    if transfer is not None:
        transfer = dict(transfer, experiments=len(spikeResults()), results=os.path.relpath(SPIKE_RESULTS, config.ROOT),
                        byBuild=transferFindings(spikeResults(), cfg.get("model"), byBuild=True))
    return dict(format=FORMAT, backend=be.name, axes=axes, workload=WORKLOAD, knobs=knobs, transfer=transfer,
                identity=[k["id"] for k in knobs if k.get("identity")])


def diff(knobs, a, b):
    """Knobs that differ between two configurations, with their change class."""
    out = {}
    for k in knobs:
        if a.get(k["id"]) != b.get(k["id"]) and (k["id"] in a or k["id"] in b):
            out[k["id"]] = dict(change=k["change"], before=a.get(k["id"]), after=b.get(k["id"]))
    return out
