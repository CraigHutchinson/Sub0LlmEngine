"""The tuning page (web/tune.html) and its small JSON API, bound to 127.0.0.1.

GET  /api/history[?machine=ID]  {machine, machines, records}
GET  /api/config                {config, file, command, running, url}
GET  /api/jobs                  the sweep queue
POST /api/apply   {param: value, slots, squadCtx}  save into the writable config layer
POST /api/sweep   {param: [values], depth: [..], ntg, B: [..], note}  queue a sweep (one at a time; refused while the engine runs)
POST /api/plan    an auto spec -> {todo, inferred, probe, retry, flagged}: gaps, gaps inferred to run out of memory, inferred cells
                  beside a working one (run to prove the edge), outliers (nothing is run)
POST /api/auto    an auto spec {axes: {name: [values]}, fixed: {param: value}, B, depth, ntg, maxRuns}: fill the view's gaps
POST /api/stop    stop the running auto job after its current run
"""
import http.server
import json
import os
import threading
import time

from . import activity, axes, bench, config, exploration, machine, process, registry


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.path = os.path.join(config.STATE_DIR, "tuning-jobs.json")
        saved = config.loadJson(self.path, {})
        self.queue = ([saved["current"]] if saved.get("current") else []) + saved.get("queue", [])
        self.current = None
        self.progress = saved.get("progress", "")
        self.done = saved.get("done", [])
        self.halt = threading.Event()
        self.log = os.path.join(config.STATE_DIR, "sweep.log")
        threading.Thread(target=self.loop, daemon=True).start()

    def add(self, grid):
        with self.lock:
            self.queue.append(grid)
            self.persist()

    def persist(self):
        """Called with the queue lock held; preserve pending work across clean restarts."""
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(dict(queue=self.queue, current=self.current, progress=self.progress, done=self.done[-10:]), f)
        os.replace(self.path + ".tmp", self.path)

    def setProgress(self, i, n, label):
        self.progress = "[%d/%d] %s" % (i + 1, n, label)

    def loop(self):
        while True:
            with self.lock:
                grid = self.queue.pop(0) if self.queue else None
                self.current = grid
                if grid is not None:
                    self.persist()
            if grid is None:
                time.sleep(1)
                continue
            try:
                cfg = grid.get("config") or config.load()
                if process.running(cfg):
                    self.progress = "refused: the engine is running at %s; stop it first (a bench needs the GPU)" % process.url(cfg)
                elif "explore" in grid:
                    self.halt.clear()
                    n = exploration.run(cfg, grid["explore"], log=self.log, progress=self.setProgress, stop=self.halt)
                    self.progress = "exploration %s after %d runs" % ("stopped" if self.halt.is_set() else "finished", n)
                elif "auto" in grid:
                    self.halt.clear()
                    n = bench.auto(cfg, grid["auto"], log=self.log, progress=self.setProgress, stop=self.halt, say=lambda m: None)
                    self.progress = "auto %s after %d runs" % ("stopped" if self.halt.is_set() else "finished", n)
                else:
                    recs = bench.sweep(cfg, grid, log=self.log, progress=self.setProgress)
                    self.progress = "finished: %d new points" % len(recs)
            except BaseException as e:  # a config error raises SystemExit
                self.progress = "failed: %s" % e
            with self.lock:
                self.done.append({"grid": grid, "result": self.progress, "ts": time.strftime("%H:%M:%S")})
                self.current = None
                self.persist()

    def state(self):
        with self.lock:
            return {"queue": list(self.queue), "current": self.current, "progress": self.progress, "done": self.done[-10:],
                    "benchmark": activity.read(), "serverPid": os.getpid(), "serverTime": time.time(), "explorationAvailable": True}


def serve(port, say=print):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    jobs = Jobs()
    page = os.path.join(config.WEB_DIR, "tune.html")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            try:
                if path in ("/", "/tune.html"):
                    with open(page, "rb") as f:
                        return self.send(200, f.read(), "text/html")
                if path == "/api/history":
                    mid = query.partition("machine=")[2] or None
                    recs = bench.history(mid)
                    gone = bench.superseded(recs)
                    for r in recs:  # failures later successes erased: shown, but not counted as failing
                        if r["outcome"] == "oom" and bench.recKey(r) in gone:
                            r["superseded"] = True
                    return self.send(200, {"machine": machine.info(), "machines": bench.machines(), "records": recs})
                if path == "/api/config":
                    cfg = config.load()
                    try:
                        cmd = process.command(cfg)
                    except SystemExit as e:
                        cmd = ["(" + str(e) + ")"]
                    return self.send(200, {"config": cfg, "file": config.writableLayer(), "command": cmd,
                                           "running": process.running(cfg), "url": process.url(cfg), "engine": process.describe(cfg),
                                           "facts": registry.facts(cfg), "cpuThreads": os.cpu_count()})
                if path == "/api/axes":
                    return self.send(200, axes.describe(config.load()))
                if path == "/api/jobs":
                    return self.send(200, jobs.state())
                self.send(404, {"error": "not found"})
            except Exception as e:
                self.send(500, {"error": str(e)})

        def do_POST(self):
            path = self.path.partition("?")[0]
            try:
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(n) or b"{}")
                if path == "/api/apply":
                    upd = {k: v for k, v in b.items() if k in set(config.PARAM_KEYS) | {"slots", "squadCtx"}}
                    f, cur = config.save(upd)
                    return self.send(200, {"file": f, "saved": cur})
                if path in ("/api/explore/plan", "/api/explore"):
                    cfg = config.load()
                    proposed = exploration.plan(cfg, b)
                    if path == "/api/explore":
                        if process.running(cfg):
                            return self.send(409, {"error": "Inference is running; stop it before queueing benchmarks."})
                        # Freeze the baseline rather than silently following later config edits.
                        jobs.add({"explore": b, "config": cfg})
                    return self.send(200, proposed)
                if path == "/api/plan":
                    return self.send(200, bench.plan(config.load(), b))
                if path == "/api/auto":
                    jobs.add({"auto": b})
                    return self.send(200, jobs.state())
                if path == "/api/stop":
                    jobs.halt.set()
                    return self.send(200, jobs.state())
                if path == "/api/sweep":
                    jobs.add({k: v for k, v in b.items() if k in set(config.PARAM_KEYS) | {"depth", "ntg", "B", "note"}})
                    return self.send(200, jobs.state())
                self.send(404, {"error": "not found"})
            except ValueError as e:
                self.send(400, {"error": str(e)})
            except Exception as e:
                self.send(500, {"error": str(e)})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    say("tuning page: http://127.0.0.1:%d/  (machine %s; Ctrl+C stops)" % (port, machine.info()["id"]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
