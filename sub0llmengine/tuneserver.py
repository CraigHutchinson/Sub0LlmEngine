"""The tuning page (web/tune.html) and its small JSON API, bound to 127.0.0.1.

GET  /api/history[?machine=ID]  {machine, machines, records}
GET  /api/config                {config, file, command, running, url}
GET  /api/jobs                  the sweep queue
POST /api/apply   {param: value, slots, squadCtx}  save into the writable config layer
POST /api/sweep   {param: [values], depth: [..], ntg, B: [..], note}  queue a sweep (one at a time; refused while the engine runs)
"""
import http.server
import json
import os
import threading
import time

from . import bench, config, machine, process


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.queue = []
        self.current = None
        self.progress = ""
        self.done = []
        self.log = os.path.join(config.STATE_DIR, "sweep.log")
        threading.Thread(target=self.loop, daemon=True).start()

    def add(self, grid):
        with self.lock:
            self.queue.append(grid)

    def setProgress(self, i, n, label):
        self.progress = "[%d/%d] %s" % (i + 1, n, label)

    def loop(self):
        while True:
            with self.lock:
                grid = self.queue.pop(0) if self.queue else None
                self.current = grid
            if grid is None:
                time.sleep(1)
                continue
            try:
                cfg = config.load()
                if process.running(cfg):
                    self.progress = "refused: the engine is running at %s; stop it first (a bench needs the GPU)" % process.url(cfg)
                else:
                    recs = bench.sweep(cfg, grid, log=self.log, progress=self.setProgress)
                    self.progress = "finished: %d new points" % len(recs)
            except BaseException as e:  # a config error raises SystemExit
                self.progress = "failed: %s" % e
            with self.lock:
                self.done.append({"grid": grid, "result": self.progress, "ts": time.strftime("%H:%M:%S")})
                self.current = None

    def state(self):
        with self.lock:
            return {"queue": list(self.queue), "current": self.current, "progress": self.progress, "done": self.done[-10:]}


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
                    return self.send(200, {"machine": machine.info(), "machines": bench.machines(), "records": bench.history(mid)})
                if path == "/api/config":
                    cfg = config.load()
                    try:
                        cmd = process.command(cfg)
                    except SystemExit as e:
                        cmd = ["(" + str(e) + ")"]
                    return self.send(200, {"config": cfg, "file": config.writableLayer(), "command": cmd,
                                           "running": process.running(cfg), "url": process.url(cfg), "engine": process.describe(cfg)})
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
                if path == "/api/sweep":
                    jobs.add({k: v for k, v in b.items() if k in set(config.PARAM_KEYS) | {"depth", "ntg", "B", "note"}})
                    return self.send(200, jobs.state())
                self.send(404, {"error": "not found"})
            except Exception as e:
                self.send(500, {"error": str(e)})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    say("tuning page: http://127.0.0.1:%d/  (machine %s; Ctrl+C stops)" % (port, machine.info()["id"]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
