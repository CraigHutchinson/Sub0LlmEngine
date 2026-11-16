"""Spike: can the engine change configuration during a job without losing a sequence's context?

One experiment is a transition A -> B between two configurations (a few knobs changed, the rest from the config):

  1. serve A; prefill a prompt of N tokens into slot 0 (the job's initial prefill)
  2. save slot 0 to a file (the backend's context transfer, from the axes definition)
  3. stop A, serve B (a load-time knob changed, so this is a restart)
  4. restore slot 0 in B; send the prompt plus a short follow-up and generate, reusing the restored prefix
  5. reference: erase the slot and run the same request in B from scratch (full prefill)

It reports whether the KV was restored, whether the output matches the from-scratch run token for token (temperature 0),
how many prompt tokens B had to recompute, and the costs (prefill in A and B, save, restart, restore). Results append to
out/spike/reconfigure.jsonl; the axes definition reads them back as each knob's `transfer` finding.

The GPU is taken with the bench lock, so queued benchmarks wait. The server binds 127.0.0.1 on a separate port.
"""
import datetime
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from . import activity, axes, backends, config, machine, registry
from .bench import GpuLock

PORT = 8093

# Transitions run by default: each isolates one question. Values are knob overrides on top of the config.
PREFILL = dict(slots=1, ubatch=2048, ctx=32768)
TRANSITIONS = [
    ("prefill-tuned to the serving config", PREFILL, {}),
    ("ubatch only", dict(PREFILL), dict(PREFILL, ubatch=512)),  # ubatch 2048 does not fit beside the serving ctx on 8 GB
    ("context and slots only", dict(slots=1, ctx=32768), {}),
    ("CPU MoE placement only", dict(nCpuMoe=34), {}),
    ("KV cache type (negative control)", dict(cacheTypeK="q8_0", cacheTypeV="q8_0"), dict(cacheTypeK="q4_0", cacheTypeV="q4_0")),
]


def post(base, path, body, timeout=1800):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read().decode("utf-8", "replace")), "status": e.code}
        except ValueError:
            return {"error": str(e), "status": e.code}


class Server:
    """llama-server for one configuration, with a slot save folder; started and stopped by the spike."""

    def __init__(self, cfg, model, slotDir, log):
        self.cfg, self.model, self.slotDir, self.log = dict(cfg, host="127.0.0.1", port=PORT), model, slotDir, log
        self.base = "http://127.0.0.1:%d" % PORT
        self.proc = None

    def __enter__(self):
        cmd = backends.get(self.cfg).serverCommand(self.cfg, self.model) + ["--slot-save-path", self.slotDir]
        self.logFile = open(self.log, "w", encoding="utf-8")
        t0 = time.time()
        self.proc = subprocess.Popen(cmd, stdout=self.logFile, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        while True:
            if self.proc.poll() is not None:
                self.loadSeconds = None
                return self
            try:
                with urllib.request.urlopen(self.base + "/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
            if time.time() - t0 > 900:
                raise RuntimeError("server did not become ready in 900 s")
            time.sleep(0.5)
        self.loadSeconds = round(time.time() - t0, 2)
        return self

    def failure(self):
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return "no log"
        kind = backends.get(self.cfg).classifyFailure(self.proc.returncode or 1, text)
        return kind + ": " + " | ".join(text.strip().splitlines()[-3:])[-400:]

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(30)
        self.logFile.close()


def promptTokens(srv, n):
    """A deterministic prompt of exactly n tokens (varied prose, so no trivially repeated blocks)."""
    parts, i = [], 0
    while len(parts) < n // 6:
        parts.append("Record %d: the %s valve at station %d reads %d.%d bar; operator %s logged it at %02d:%02d." % (
            i, ["north", "east", "south", "west"][i % 4], i * 7 % 113, i * 13 % 97, i % 10, "ABCDEFGH"[i % 8], i % 24, i * 17 % 60))
        i += 1
    toks = post(srv.base, "/tokenize", {"content": " ".join(parts)}).get("tokens", [])
    while len(toks) < n:
        toks += toks
    return toks[:n]


def complete(srv, tokens, nPredict, cache=True):
    r = post(srv.base, "/completion", {"prompt": tokens, "n_predict": nPredict, "id_slot": 0, "cache_prompt": cache,
                                       "temperature": 0, "top_k": 1, "seed": 1, "return_tokens": True})
    t = r.get("timings", {}) if isinstance(r, dict) else {}
    return dict(error=r.get("error"), promptN=t.get("prompt_n"), promptMs=t.get("prompt_ms"), predictedN=t.get("predicted_n"),
                predictedMs=t.get("predicted_ms"), cached=r.get("tokens_cached"), tokens=r.get("tokens"), text=r.get("content"))


def notReused(log):
    """Why the server re-processed a restored prefix, from its log."""
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    if "forcing full prompt re-processing" in text:
        return ("restored, then discarded: the server needs a context checkpoint to reuse a hybrid/recurrent prefix "
                "(server-context.cpp: pos_min >= pos_next - n_swa - 1) and slot files carry no checkpoints")
    return "restored, then re-processed (cause not in the log)"


def transition(cfg, name, a, b, n=16384, follow=64, nPredict=32, control=True, say=print):
    model, _ = registry.resolve(cfg)
    knobs = backends.get(cfg).knobs()
    ca, cb = dict(cfg, **a), dict(cfg, **b)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    slotDir = os.path.join(axes.SPIKE_DIR, "slots")
    os.makedirs(slotDir, exist_ok=True)
    rec = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), machine=machine.info()["id"], name=name,
               model=cfg.get("model"), architecture=(registry.facts(cfg) or {}).get("architecture"), build=backends.get(cfg).buildLabel(cfg), promptTokens=n, followTokens=follow,
               configA={k["id"]: ca.get(k["id"]) for k in knobs if k["change"] == "load"},
               configB={k["id"]: cb.get(k["id"]) for k in knobs if k["change"] == "load"},
               changed=axes.diff([k for k in knobs if k["change"] == "load"], ca, cb), restored=None, identical=None)
    fname = "spike-%s.bin" % stamp
    activity.write(phase="spike", message="Spike %s: prefilling %d tokens in A" % (name, n))
    with Server(ca, model, slotDir, os.path.join(axes.SPIKE_DIR, "server-A.log")) as srv:
        if srv.loadSeconds is None:
            rec["error"] = "A did not start: " + srv.failure()
            return rec
        rec["loadA"] = srv.loadSeconds
        toks = promptTokens(srv, n + follow)
        base, extra = toks[:n], toks
        # prefill only: a generated token would sit past the prompt, and hybrid/recurrent memory cannot roll it back later
        first = complete(srv, base, 0)
        rec["prefillA"] = {k: first[k] for k in ("promptN", "promptMs", "error")}
        saved = post(srv.base, "/slots/0?action=save", {"filename": fname})
        rec["save"] = {"tokens": saved.get("n_saved"), "bytes": saved.get("n_written"), "ms": (saved.get("timings") or {}).get("save_ms"),
                       "error": saved.get("error")}
    say("  A: load %.1fs, prefill %s ms, save %s" % (rec["loadA"], rec["prefillA"]["promptMs"], rec["save"]))
    activity.write(phase="spike", message="Spike %s: restoring into B" % name)
    with Server(cb, model, slotDir, os.path.join(axes.SPIKE_DIR, "server-B.log")) as srv:
        if srv.loadSeconds is None:
            rec["error"] = "B did not start: " + srv.failure()
            return rec
        rec["loadB"] = srv.loadSeconds
        restored = post(srv.base, "/slots/0?action=restore", {"filename": fname})
        rec["restore"] = {"tokens": restored.get("n_restored"), "bytes": restored.get("n_read"),
                          "ms": (restored.get("timings") or {}).get("restore_ms"), "error": restored.get("error")}
        rec["restored"] = bool(restored.get("n_restored")) and not restored.get("error")
        after = complete(srv, extra, nPredict)
        rec["afterRestore"] = {k: after[k] for k in ("promptN", "promptMs", "predictedN", "predictedMs", "cached", "error")}
        post(srv.base, "/slots/0?action=erase", {})
        fresh = complete(srv, extra, nPredict, cache=False)
        rec["fresh"] = {k: fresh[k] for k in ("promptN", "promptMs", "predictedN", "predictedMs", "error")}
        if after["error"] or fresh["error"]:
            rec["identical"] = None  # no verdict: a request failed (see afterRestore / fresh)
            rec["error"] = "generation failed: " + str(after["error"] or fresh["error"])[:300]
        elif after["tokens"] is not None:
            rec["identical"] = bool(after["tokens"]) and after["tokens"] == fresh["tokens"]
            # how far the two greedy continuations agree: a late divergence is numeric noise (another ubatch sums in
            # another order), a divergence at token 0 points at the restored state
            agree = 0
            while agree < min(len(after["tokens"]), len(fresh["tokens"] or [])) and after["tokens"][agree] == fresh["tokens"][agree]:
                agree += 1
            rec["agreeTokens"] = agree
        else:
            rec["identical"] = bool(after["text"]) and after["text"] == fresh["text"]
        rec["outputs"] = {"afterRestore": (after["text"] or "")[:160], "fresh": (fresh["text"] or "")[:160]}
        if control and not rec["identical"] and rec["restored"]:
            # Control: the same split (prefill the prompt, then continue) inside B with no save/restore. Matching the
            # restored run means the difference comes from splitting the prefill, not from moving the KV.
            post(srv.base, "/slots/0?action=erase", {})
            complete(srv, base, 0)
            split = complete(srv, extra, nPredict)
            rec["control"] = {"splitInB": {k: split[k] for k in ("promptN", "promptMs", "error")},
                              "matchesRestored": split["tokens"] == after["tokens"], "matchesFresh": split["tokens"] == fresh["tokens"]}
            if rec["control"]["matchesRestored"]:
                rec["transferFaithful"] = True  # the restored KV behaves exactly like KV computed in B
    # Reused: B recomputed only the follow-up (a few tokens of slack), not the restored prefix.
    rec["reused"] = bool(rec["restored"]) and rec["afterRestore"]["promptN"] is not None and rec["afterRestore"]["promptN"] <= follow + 8
    if rec["restored"] and not rec["reused"]:
        rec["note"] = notReused(os.path.join(axes.SPIKE_DIR, "server-B.log"))
    try:
        os.remove(os.path.join(slotDir, fname))
    except OSError:
        pass
    # Derived: what the switch cost and what reuse saved, in seconds
    ms = lambda x: (x or 0) / 1000
    if rec["restored"]:
        rec["switchSeconds"] = round(ms(rec["save"]["ms"]) + rec["loadB"] + ms(rec["restore"]["ms"]), 2)
        rec["reuseSavedSeconds"] = round(ms(rec["fresh"]["promptMs"]) - ms(rec["afterRestore"]["promptMs"]), 2)
        rec["prefillGainSeconds"] = round(ms(rec["fresh"]["promptMs"]) * n / max(rec["fresh"]["promptN"] or 1, 1) - ms(rec["prefillA"]["promptMs"]), 2)
    return rec


def transitions(cfg):
    """The default transitions for this model: a dense model (no expert layers in the registry facts) swaps the CPU MoE
    transition for a GPU-layers one, the placement knob it actually has."""
    try:
        facts = registry.facts(cfg) or {}
    except (SystemExit, Exception):
        facts = {}
    out = list(TRANSITIONS)
    if not facts.get("expertLayers"):
        layers = int(cfg.get("gpuLayers", 99))
        layers = layers if layers < (facts.get("blockCount") or 999) else (facts.get("blockCount") or 64)
        out = [t if t[0] != "CPU MoE placement only" else ("GPU layers only", dict(gpuLayers=max(layers - 4, 0)), dict(gpuLayers=layers))
               for t in out]
    return out


def run(cfg, which=None, n=16384, say=print):
    os.makedirs(axes.SPIKE_DIR, exist_ok=True)
    out = []
    with GpuLock():
        for i, (name, a, b) in enumerate(transitions(cfg)):
            if which and i not in which:
                continue
            say("spike %d: %s  A=%s  B=%s" % (i, name, a or "config", b or "config"))
            try:
                rec = transition(cfg, name, a, b, n=n, say=say)
            except Exception as e:  # one failed experiment must not stop the rest
                rec = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), name=name, error=repr(e), restored=None)
            with open(axes.SPIKE_RESULTS, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            say("  -> restored=%s identical=%s recomputed=%s switch=%ss saved=%ss %s" % (
                rec.get("restored"), rec.get("identical"), (rec.get("afterRestore") or {}).get("promptN"),
                rec.get("switchSeconds"), rec.get("reuseSavedSeconds"), rec.get("error") or ""))
            out.append(rec)
    activity.write(phase="idle", message="Spike finished: %d experiment(s)" % len(out))
    return out
