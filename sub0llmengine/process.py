"""Start, stop and inspect the engine server process.

`start` records what it started in out/engine.json (format sub0llmengine.engine.v1: the effective configuration, the
resolved model, the build label and the exact command), so `status --json` can tell a client which weights, build and
settings are answering, and whether they still match the configuration it was given.
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import backends, config, platform, registry

PID_FILE = os.path.join(config.STATE_DIR, "engine.pid")
LOG_FILE = os.path.join(config.STATE_DIR, "engine.log")
STATE_FILE = os.path.join(config.STATE_DIR, "engine.json")
LOCK_FILE = os.path.join(config.STATE_DIR, "bench.lock")  # the bench's GPU lock (bench.GpuLock)
FORMAT = "sub0llmengine.engine.v1"
# Pool watermark levels: the share of the KV pool held by busy slots (see pool()).
POOL_LEVELS = [(0.95, "critical"), (0.85, "warning"), (0.70, "notice")]
# Settings that change what a client gets (a running engine with other values is "not the configured engine").
SERVING_KEYS = ["model", "alias", "host", "port", "slots", "kvUnifiedPerSlot", "ctxCheckpoints", "cacheRam", "extraArgs"]


def fetch(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def probe(u, timeout=3):
    """(HTTP status, body) for a GET, or (None, None) when nothing answers."""
    try:
        with urllib.request.urlopen(u, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read().decode("utf-8", "replace")
    except Exception:
        return None, None


def url(cfg):
    host = cfg.get("host", "127.0.0.1")
    return "http://%s:%s" % ("127.0.0.1" if host in ("0.0.0.0", "::") else host, cfg.get("port", 8092))


def health(cfg):
    """"ok" when the server answers, "loading" while it loads the model (llama-server answers 503), else None."""
    code, _ = probe(url(cfg) + "/health")
    if code == 200:
        return "ok"
    return "loading" if code == 503 else None


def running(cfg):
    return health(cfg) == "ok"


def starting(cfg):
    """A server this tool started is loading: it answers 503, or its process lives but does not listen yet."""
    if health(cfg) == "loading":
        return True
    p, st = pid(), state()
    return bool(p and st and alive(p) and st.get("url") == url(cfg) + "/v1")


def command(cfg):
    model, _ = registry.resolve(cfg)
    return backends.get(cfg).serverCommand(cfg, model)


def pid():
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def state():
    """What `start` recorded about the engine it started, or None."""
    return config.loadJson(STATE_FILE)


def benchLockOwner():
    """The pid text in the bench's GPU lock when a live bench holds it, else None (a lock left by a crashed bench, whose
    owner no longer exists, does not count; the next bench sets it aside)."""
    return platform.lockOwner(LOCK_FILE)


def model(cfg, ref=None):
    """The configured model: reference, registry id, file path, whether it exists, and the registry's facts."""
    ref = ref or cfg.get("model")
    path, rid = registry.resolve(cfg, ref)
    return {"ref": ref, "id": rid, "path": path, "exists": os.path.isfile(path), "facts": registry.facts(cfg, ref)}


def identity(cfg):
    """The settings that define what is served: the knobs of a measured point plus the serving keys."""
    be = backends.get(cfg)
    keys = list(be.selectionParams()) + SERVING_KEYS
    identity = {"backend": cfg.get("backend", "llamacpp"), **{k: cfg.get(k) for k in keys}}
    fingerprint = be.selectionFingerprint(cfg)
    if fingerprint is not None:
        identity["backendConfigFingerprint"] = fingerprint
    return identity


def differences(cfg, recorded, recordedIdentity=None):
    """Keys whose configured value differs from the recorded engine's: {key: [recorded, configured]}."""
    a, b = recordedIdentity or identity(recorded), identity(cfg)
    if a.get("backend") != b.get("backend"):
        keys = dict.fromkeys(["backend"] + SERVING_KEYS + list(backends.get(cfg).selectionParams()) +
                             ["backendConfigFingerprint"])
    else:
        keys = dict.fromkeys(list(a) + list(b))
    return {k: [a.get(k), b.get(k)] for k in keys if a.get(k) != b.get(k)}


def record(cfg, cmd, p):
    m = model(cfg)
    m.pop("facts")
    st = {"format": FORMAT, "pid": p, "url": url(cfg) + "/v1", "startedAt": datetime.datetime.now().isoformat(timespec="seconds"),
          "backend": cfg.get("backend", "llamacpp"), "build": backends.get(cfg).buildLabel(cfg), "model": m,
          "config": cfg, "identity": identity(cfg), "configLayers": [x for x in config.layers() if os.path.exists(x)],
          "command": cmd, "log": LOG_FILE}
    with open(STATE_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    return st


def forget():
    for f in (PID_FILE, STATE_FILE):
        try:
            os.remove(f)
        except OSError:
            pass


def start(cfg, wait=True, say=print):
    """0: answering (already, or started and ready); 1: failed to start; 2: refused (a bench holds the GPU)."""
    if running(cfg):
        st = state()
        diff = differences(cfg, st["config"], st.get("identity")) if st else None
        if diff:
            say("engine: already answering at %s, started with other settings: %s (stop it first to apply them)" % (url(cfg), json.dumps(diff)))
        elif st is None:
            say("engine: already answering at %s (not started by this tool; its settings are unknown)" % url(cfg))
        else:
            say("engine: already answering at %s" % url(cfg))
        return 0
    if starting(cfg):
        say("engine: already starting at %s (loading the model)" % url(cfg))
        if not wait:
            return 0
        for _ in range(360):
            if running(cfg):
                status(cfg, say)
                return 0
            if not starting(cfg):
                say("engine: stopped while loading; see %s" % LOG_FILE)
                return 1
            time.sleep(1)
        return 1
    owner = benchLockOwner()
    if owner:
        say("engine: a bench holds the GPU (%s, pid %s); start the engine when it finishes" % (LOCK_FILE, owner))
        return 2
    os.makedirs(config.STATE_DIR, exist_ok=True)
    cmd = command(cfg)
    say("engine: " + " ".join(cmd))
    p = platform.spawnDetached(cmd, LOG_FILE)
    with open(PID_FILE, "w") as f:
        f.write(str(p.pid))
    record(cfg, cmd, p.pid)
    say("engine: pid %d, log %s" % (p.pid, LOG_FILE))
    if not wait:
        return 0
    for _ in range(360):
        if running(cfg):
            say("engine: ready")
            status(cfg, say)
            return 0
        if p.poll() is not None:
            say("engine: exited with code %s; end of the log:" % p.returncode)
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                say("".join(f.readlines()[-15:]))
            forget()
            return 1
        time.sleep(1)
    say("engine: not answering after 6 minutes; see %s" % LOG_FILE)
    return 1


def alive(p):
    return platform.alive(p)


def stop(cfg, say=print, timeout=30):
    """Stops the engine this tool started and waits until it has gone. 0: stopped or nothing to stop; 1: still answering."""
    p = pid()
    if not p:
        if running(cfg):
            say("engine: answering at %s but not started by this tool (no pid file); stop it where it was started" % url(cfg))
            return 1
        say("engine: not running")
        forget()
        return 0
    try:
        platform.terminate(p)
    except OSError as e:
        say("engine: pid %d: %s" % (p, e))
    for _ in range(timeout * 2):
        if not alive(p) and not running(cfg):
            break
        time.sleep(0.5)
    else:
        say("engine: pid %d still running after %d s" % (p, timeout))
        return 1
    forget()
    say("engine: stopped pid %d" % p)
    return 0


def describe(cfg):
    """The answering engine as the server reports it, or None when nothing answers."""
    u = url(cfg)
    if not running(cfg):
        return None
    if cfg.get("backend", "llamacpp") == "llamacpp":
        props = json.loads(fetch(u + "/props") or "{}")
        slots = json.loads(fetch(u + "/slots") or "[]")
        slots = slots if isinstance(slots, list) else []
        nctx = props.get("default_generation_settings", {}).get("n_ctx")
        return {"url": u + "/v1", "alias": props.get("model_alias") or cfg.get("alias"), "slots": len(slots) or cfg.get("slots"),
                "busy": sum(1 for s in slots if s.get("is_processing")), "nCtxPerSlot": nctx, "pid": pid(), "slotList": slots}
    try:
        health_data = json.loads(fetch(u + "/health") or "{}")
    except ValueError:
        health_data = {}
    if not isinstance(health_data, dict):
        health_data = {}
    try:
        models = json.loads(fetch(u + "/v1/models") or "{}")
    except ValueError:
        models = {}
    data = models.get("data", []) if isinstance(models, dict) else []
    data = data if isinstance(data, list) else []
    model = data[0] if data and isinstance(data[0], dict) else {}
    model_alias = model.get("id")
    context_sources = (health_data, model)
    nctx = next((source[k] for source in context_sources for k in ("max_context", "context_length", "max_model_len", "context")
                 if isinstance(source.get(k), int) and not isinstance(source.get(k), bool)), None)
    return {"url": u + "/v1", "alias": cfg.get("alias") or model_alias or health_data.get("model") or "unknown",
            "slots": cfg.get("slots") or 1, "busy": None, "nCtxPerSlot": nctx, "pid": pid(), "slotList": []}


def pool(cfg, slots):
    """The KV pool watermark from llama-server's /slots (it reports none itself).

    With unified KV all slots share one pool of `ctx` token cells; otherwise each slot has its own `n_ctx` and the pool is
    their sum. A slot's cached tokens (`n_prompt_tokens`: prompt plus generated) are "used" while it processes and
    "reclaimable" when idle (the server clears idle slots when the pool runs short). A prefix shared by two slots is
    counted twice, so the figures err on the safe side. level: ok / notice (70 % used) / warning (85 %) / critical (95 %)."""
    if not slots:
        return None
    held = [int(s.get("n_prompt_tokens") or 0) for s in slots]
    busy = [s.get("is_processing", False) for s in slots]
    if cfg.get("kvUnified", True):
        size = int(cfg.get("ctx") or 0) or max(int(s.get("n_ctx") or 0) for s in slots)
    else:
        size = sum(int(s.get("n_ctx") or 0) for s in slots)
    used = sum(h for h, b in zip(held, busy) if b)
    reclaimable = sum(h for h, b in zip(held, busy) if not b)
    share = used / size if size else 0.0
    level = next((name for limit, name in POOL_LEVELS if share >= limit), "ok")
    return {"size": size, "used": used, "reclaimable": reclaimable, "free": max(0, size - used), "usedShare": round(share, 3),
            "busySlots": sum(busy), "slots": len(slots), "level": level,
            "perSlot": [{"id": s.get("id"), "tokens": h, "busy": b, "nCtx": s.get("n_ctx")} for s, h, b in zip(slots, held, busy)]}


def info(cfg):
    """Everything a client needs, as one JSON-able dict (format sub0llmengine.engine.v1). See README "Using the engine from
    another project"."""
    d = describe(cfg)
    st = state()
    out = {"format": FORMAT, "running": d is not None, "url": url(cfg) + "/v1", "health": url(cfg) + "/health",
           "benchLock": benchLockOwner()}
    if d:
        out.update({k: d[k] for k in ("alias", "slots", "busy", "nCtxPerSlot", "pid")})
        out["squadCtx"] = cfg.get("squadCtx") or d["nCtxPerSlot"]
        out["pool"] = pool(st["config"] if st else cfg, d["slotList"])
    else:
        out["loading"] = starting(cfg)
    if st and d:
        diff = differences(cfg, st["config"], st.get("identity"))
        out.update({"startedByThisTool": True, "startedAt": st.get("startedAt"), "build": st.get("build"), "model": st.get("model"),
                    "config": st.get("config"), "command": st.get("command"), "matchesConfig": not diff, "differences": diff})
    else:
        out["startedByThisTool"] = False
        if d:
            out["matchesConfig"] = None  # something else answers here; its settings are unknown
    return out


def status(cfg, say=print):
    d = describe(cfg)
    if not d:
        say("engine: %s at %s" % ("loading the model" if starting(cfg) else "not answering", url(cfg)))
        return 1
    shown = dict(d, busy=d["busy"] if d["busy"] is not None else "unknown",
                 nCtxPerSlot=d["nCtxPerSlot"] if d["nCtxPerSlot"] is not None else "unknown")
    say("engine: %(url)s  model=%(alias)s  slots=%(slots)s (busy %(busy)s)  n_ctx per slot=%(nCtxPerSlot)s  pid=%(pid)s" % shown)
    st = state()
    if st:
        diff = differences(cfg, st["config"], st.get("identity"))
        say("        %s  %s  started %s%s" % (st["model"].get("id") or st["model"].get("path"), st.get("build"), st.get("startedAt"),
                                             ("  DIFFERS from the configuration: " + json.dumps(diff)) if diff else ""))
    pl = pool(st["config"] if st else cfg, d["slotList"])
    if pl:
        say("pool:   %(used)d of %(size)d tokens held by %(busySlots)d busy slot(s), %(free)d free, %(reclaimable)d reclaimable from idle slots (%(level)s)" % pl)
    say("squad:  --engine %s=%s,model=%s,ctx=%s,slots=%s" % (d["alias"], d["url"], d["alias"], cfg.get("squadCtx") or d["nCtxPerSlot"], d["slots"]))
    return 0


def err(msg):
    print(msg, file=sys.stderr, flush=True)
