"""Receive a tuning-map export against local evidence; never activate or restart an engine.

The exporter proposes one observed point. Local history is the source of truth; metrics in
the submitted file are not trusted. Server request validation is a separate receiving gate.
"""
import math

from . import backends


def validate(profile, records, host_id, build):
    """Return a config layer and consumer budget, or reject unverifiable evidence."""
    if not isinstance(profile, dict) or profile.get("schema") != "sub0llmengine.measured-selection.v1":
        raise ValueError("unsupported measured-selection schema")
    identity = profile.get("identity", {})
    proposed = profile.get("engineConfig", {})
    evidence = profile.get("evidence", {})
    budget = profile.get("consumerBudget", {})
    if not all(isinstance(x, dict) for x in (identity, proposed, evidence, budget)):
        raise ValueError("selection sections must be objects")
    if any(not isinstance(identity.get(k), str) or not identity[k] for k in ("machine", "backend", "model", "build")):
        raise ValueError("selection identity is incomplete")
    if identity["machine"] != host_id or identity["build"] != build:
        raise ValueError("selection machine/build does not match this host and configured engine build")
    if any(proposed.get(k) != identity[k] for k in ("backend", "model")):
        raise ValueError("configuration and evidence identity disagree")
    keys = backends.get(proposed).selectionParams()
    allowed = set(keys) | {"backend", "model", "slots", "squadCtx"}
    if set(proposed) != allowed or any(proposed.get(k) is None for k in keys):
        raise ValueError("selection must contain exactly the backend's measured knobs and consumer settings")
    depth, b, ntg = (evidence.get(k) for k in ("depth", "concurrency", "generatedTokens"))
    if any(type(v) is not int or v <= 0 for v in (depth, b, ntg)):
        raise ValueError("measured workload must contain positive integer depth, concurrency and output length")
    if not backends.get(proposed).fitsBench(proposed, depth, ntg, b):
        raise ValueError("measured workload exceeds the configured context")
    expected = {"maxConcurrentRequests": b, "maxPromptTokens": depth, "maxOutputTokens": ntg, "maxTotalTokens": depth + ntg}
    requirements = profile.get("requirements", {})
    if not isinstance(requirements, dict):
        raise ValueError("requirements must be an object")
    minimum = requirements.get("minSlotContext", 0)
    if type(minimum) is not int or minimum < 0 or min(depth + ntg, proposed["ctx"] / b) < minimum:
        raise ValueError("selection does not cover its required minimum context per slot")
    if budget != expected or proposed["slots"] != b or proposed["squadCtx"] != depth + ntg:
        raise ValueError("consumer budget must match the observed workload, not the allocated context")
    params = {k: proposed[k] for k in keys}
    matches = [r for r in records if not r.get("excluded")
               and all(r.get(k) == v for k, v in identity.items())
               and r.get("params") == params and r.get("depth") == depth
               and r.get("B") == b and r.get("ntg") == ntg]
    # The page's rule: a failure heals once two later passes of this exact point worked (a glitch must not withhold it).
    oks = [r for r in matches if r.get("outcome") == "ok"]
    live = [f for f in matches if f.get("outcome") != "ok"
            and len({r.get("ts") for r in oks if str(r.get("ts")) > str(f.get("ts"))}) < 2]
    if not oks or live:
        raise ValueError("no unconflicted local success for this exact selection; re-measure first")
    matches = oks
    if any(type(r.get("tgTps")) not in (int, float) or not math.isfinite(r["tgTps"]) or r["tgTps"] <= 0 for r in matches):
        raise ValueError("local throughput evidence is invalid; re-measure first")
    return {"engineConfig": dict(proposed), "consumerBudget": expected, "localPasses": len(matches),
            "serverValidated": False, "activation": "review then start separately"}
