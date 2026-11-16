"""Start, stop and inspect the engine server process."""
import json
import os
import signal
import subprocess
import time
import urllib.request

from . import backends, config, registry

PID_FILE = os.path.join(config.STATE_DIR, "engine.pid")
LOG_FILE = os.path.join(config.STATE_DIR, "engine.log")


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


def start(cfg, wait=True, say=print):
    if running(cfg):
        say("engine: already answering at %s" % url(cfg))
        return 0
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
    say("engine: pid %d, log %s" % (p.pid, LOG_FILE))
    if not wait:
        return 0
    for _ in range(360):
        if running(cfg):
            say("engine: ready")
            return status(cfg, say)
        if p.poll() is not None:
            say("engine: exited with code %s; end of the log:" % p.returncode)
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                say("".join(f.readlines()[-15:]))
            return 1
        time.sleep(1)
    say("engine: not answering after 6 minutes; see %s" % LOG_FILE)
    return 1


def stop(cfg, say=print):
    p = pid()
    if not p:
        say("engine: no pid file (not started by this tool)")
        return 0
    try:
        if config.IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], capture_output=True)
        else:
            os.kill(p, signal.SIGTERM)
        say("engine: stopped pid %d" % p)
    except Exception as e:
        say("engine: could not stop pid %d: %s" % (p, e))
    os.remove(PID_FILE)
    return 0


def describe(cfg):
    u = url(cfg)
    if not running(cfg):
        return None
    props = json.loads(fetch(u + "/props") or "{}")
    slots = json.loads(fetch(u + "/slots") or "[]")
    slots = slots if isinstance(slots, list) else []
    nctx = props.get("default_generation_settings", {}).get("n_ctx")
    return {"url": u + "/v1", "alias": props.get("model_alias") or cfg.get("alias"), "slots": len(slots) or cfg.get("slots"),
            "busy": sum(1 for s in slots if s.get("is_processing")), "nCtxPerSlot": nctx, "pid": pid()}


def status(cfg, say=print):
    d = describe(cfg)
    if not d:
        say("engine: not answering at %s" % url(cfg))
        return 1
    say("engine: %(url)s  model=%(alias)s  slots=%(slots)s (busy %(busy)s)  n_ctx per slot=%(nCtxPerSlot)s  pid=%(pid)s" % d)
    say("squad:  --engine %s=%s,model=%s,ctx=%s,slots=%s" % (d["alias"], d["url"], d["alias"], cfg.get("squadCtx") or d["nCtxPerSlot"], d["slots"]))
    return 0
