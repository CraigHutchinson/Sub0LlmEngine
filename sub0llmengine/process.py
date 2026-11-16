"""Start, stop and inspect the engine server process.

`start` records what it started in out/engine.json (format sub0llmengine.engine.v1: the effective configuration, the
resolved model, the build label and the exact command), so `status --json` can tell a client which weights, build and
settings are answering, and whether they still match the configuration it was given.
"""
import datetime
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

from . import backends, config, registry

PID_FILE = os.path.join(config.STATE_DIR, "engine.pid")
LOG_FILE = os.path.join(config.STATE_DIR, "engine.log")
STATE_FILE = os.path.join(config.STATE_DIR, "engine.json")
LOCK_FILE = os.path.join(config.STATE_DIR, "bench.lock")  # the bench's GPU lock (bench.GpuLock)
FORMAT = "sub0llmengine.engine.v1"
# Settings that change what a client gets (a running engine with other values is "not the configured engine").
SERVING_KEYS = ["model", "alias", "host", "port", "slots", "ctxCheckpoints", "cacheRam", "extraArgs"]


def fetch(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def url(cfg):
    host = cfg.get("host", "127.0.0.1")
    return "http://%s:%s" % ("127.0.0.1" if host in ("0.0.0.0", "::") else host, cfg.get("port", 8092))


def running(cfg):
    return fetch(url(cfg) + "/health") is not None


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
    """The pid text in the bench's GPU lock when a bench holds it, else None."""
    try:
        with open(LOCK_FILE) as f:
            return f.read().strip() or "unknown"
    except OSError:
        return None


def model(cfg, ref=None):
    """The configured model: reference, registry id, file path, whether it exists, and the registry's facts."""
    ref = ref or cfg.get("model")
    path, rid = registry.resolve(cfg, ref)
    return {"ref": ref, "id": rid, "path": path, "exists": os.path.isfile(path), "facts": registry.facts(cfg, ref)}


def identity(cfg):
    """The settings that define what is served: the knobs of a measured point plus the serving keys."""
    keys = list(backends.get(cfg).selectionParams()) + SERVING_KEYS
    return {k: cfg.get(k) for k in keys}


def differences(cfg, recorded):
    """Keys whose configured value differs from the recorded engine's: {key: [recorded, configured]}."""
    a, b = identity(recorded), identity(cfg)
    return {k: [a[k], b[k]] for k in b if a.get(k) != b[k]}


def record(cfg, cmd, p):
    m = model(cfg)
    m.pop("facts")
    st = {"format": FORMAT, "pid": p, "url": url(cfg) + "/v1", "startedAt": datetime.datetime.now().isoformat(timespec="seconds"),
          "backend": cfg.get("backend", "llamacpp"), "build": backends.get(cfg).buildLabel(cfg), "model": m,
          "config": cfg, "configLayers": [x for x in config.layers() if os.path.exists(x)], "command": cmd, "log": LOG_FILE}
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
        diff = differences(cfg, st["config"]) if st else None
        if diff:
            say("engine: already answering at %s, started with other settings: %s (stop it first to apply them)" % (url(cfg), json.dumps(diff)))
        elif st is None:
            say("engine: already answering at %s (not started by this tool; its settings are unknown)" % url(cfg))
        else:
            say("engine: already answering at %s" % url(cfg))
        return 0
    owner = benchLockOwner()
    if owner:
        say("engine: a bench holds the GPU (%s, pid %s); start the engine when it finishes" % (LOCK_FILE, owner))
        return 2
    os.makedirs(config.STATE_DIR, exist_ok=True)
    cmd = command(cfg)
    say("engine: " + " ".join(cmd))
    flags = 0
    if config.IS_WINDOWS:  # outlive this console; below-normal priority so the desktop stays responsive
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | 0x00004000
    with open(LOG_FILE, "w", encoding="utf-8") as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                             start_new_session=not config.IS_WINDOWS)
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
    if config.IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % p, "/NH"], capture_output=True, text=True).stdout
        return str(p) in out
    try:
        os.kill(p, 0)
        return True
    except OSError:
        return False


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
        if config.IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], capture_output=True)
        else:
            os.kill(p, signal.SIGTERM)
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
    props = json.loads(fetch(u + "/props") or "{}")
    slots = json.loads(fetch(u + "/slots") or "[]")
    slots = slots if isinstance(slots, list) else []
    nctx = props.get("default_generation_settings", {}).get("n_ctx")
    return {"url": u + "/v1", "alias": props.get("model_alias") or cfg.get("alias"), "slots": len(slots) or cfg.get("slots"),
            "busy": sum(1 for s in slots if s.get("is_processing")), "nCtxPerSlot": nctx, "pid": pid()}


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
    if st and d:
        out.update({"startedByThisTool": True, "startedAt": st.get("startedAt"), "build": st.get("build"), "model": st.get("model"),
                    "config": st.get("config"), "command": st.get("command"), "matchesConfig": not differences(cfg, st["config"]),
                    "differences": differences(cfg, st["config"])})
    else:
        out["startedByThisTool"] = False
        if d:
            out["matchesConfig"] = None  # something else answers here; its settings are unknown
    return out


def status(cfg, say=print):
    d = describe(cfg)
    if not d:
        say("engine: not answering at %s" % url(cfg))
        return 1
    say("engine: %(url)s  model=%(alias)s  slots=%(slots)s (busy %(busy)s)  n_ctx per slot=%(nCtxPerSlot)s  pid=%(pid)s" % d)
    st = state()
    if st:
        diff = differences(cfg, st["config"])
        say("        %s  %s  started %s%s" % (st["model"].get("id") or st["model"].get("path"), st.get("build"), st.get("startedAt"),
                                             ("  DIFFERS from the configuration: " + json.dumps(diff)) if diff else ""))
    say("squad:  --engine %s=%s,model=%s,ctx=%s,slots=%s" % (d["alias"], d["url"], d["alias"], cfg.get("squadCtx") or d["nCtxPerSlot"], d["slots"]))
    return 0


def err(msg):
    print(msg, file=sys.stderr, flush=True)
