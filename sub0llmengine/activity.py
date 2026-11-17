"""Small cross-process benchmark status file. A heartbeat is not proof of forward progress."""
import json
import os
import time

from . import config, platform


def cpu_seconds(pid):
    """Child CPU seconds without launching a monitoring subprocess (None when it cannot be read)."""
    return platform.cpuSeconds(pid)


def write(**state):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    path = os.path.join(config.STATE_DIR, "bench-activity.json")
    state.update(heartbeatAt=time.time(), ownerPid=os.getpid())
    # A heartbeat must never fail a bench: atomicWrite retries while a Windows reader (the page's poll, an indexer)
    # holds the file, then skips this beat.
    platform.atomicWrite(path, json.dumps(state))


def read():
    state = config.loadJson(os.path.join(config.STATE_DIR, "bench-activity.json"), {})
    if state:
        state["heartbeatAgeSeconds"] = max(0, round(time.time() - state["heartbeatAt"], 1))
    return state
