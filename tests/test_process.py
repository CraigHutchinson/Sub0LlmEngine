"""The integration surface without a GPU: config layering, model resolution, the server command, and the engine
description a client reads (status --json), against a stub llama-server on a free local port."""
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from sub0llmengine import config, process, registry
from sub0llmengine.backends import llamacpp


class StubServer(http.server.BaseHTTPRequestHandler):
    """Answers /health, /props and /slots like llama-server with 2 slots of 8192 tokens, one busy (3000 tokens held) and one
    idle (1000 held). With loading = True it answers 503 everywhere, as llama-server does while it loads the model."""
    loading = False

    def do_GET(self):
        if self.loading:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "Loading model", "code": 503}}')
            return
        body = {"/health": {"status": "ok"},
                "/props": {"model_alias": "stub", "default_generation_settings": {"n_ctx": 8192}},
                "/slots": [{"id": 0, "n_ctx": 8192, "is_processing": True, "n_prompt_tokens": 3000},
                           {"id": 1, "n_ctx": 8192, "is_processing": False, "n_prompt_tokens": 1000}]}.get(self.path)
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body or {}).encode())

    def log_message(self, *a):
        pass


def deadPid():
    """The pid of a process that has exited."""
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, val in [("STATE_DIR", self.dir)]:
            p = mock.patch.object(config, name, val)
            p.start()
            self.addCleanup(p.stop)
        for name in ("PID_FILE", "LOG_FILE", "STATE_FILE", "LOCK_FILE"):
            p = mock.patch.object(process, name, os.path.join(self.dir, os.path.basename(getattr(process, name))))
            p.start()
            self.addCleanup(p.stop)
        # a fake binary folder and model file, so commands resolve without llama.cpp or a registry
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        for n in ("llama-server", "llama-batched-bench"):
            write(os.path.join(self.bin, n + llamacpp.EXE), "")
        self.model = os.path.join(self.dir, "m.gguf")
        write(self.model, "")
        llamacpp.LlamaCpp._help[self.bin] = "--no-mmap ..."  # an older build's --help (no --load-mode)

    def cfg(self, **kw):
        base = dict(backend="llamacpp", binDir=self.bin, model=self.model, alias="stub", host="127.0.0.1", port=1, ctx=16384,
                    slots=2, nCpuMoe=30, gpuLayers=99, ubatch=512, batch=2048, threads=8, cacheTypeK="q8_0", cacheTypeV="q8_0",
                    flashAttn="on", kvUnified=True, mmap=False, squadCtx=None, extraArgs=[])
        base.update(kw)
        return base


class TestConfig(Tmp):
    def test_layers_later_wins_and_comments_drop(self):
        a, b = os.path.join(self.dir, "a.json"), os.path.join(self.dir, "b.json")
        write(a, {"_note": "x", "ctx": 1, "slots": 2})
        write(b, {"ctx": 3})
        with mock.patch.object(config, "layers", lambda: [a, b]):
            self.assertEqual(config.load(), {"ctx": 3, "slots": 2})

    def test_writable_layer_is_the_top_extra_layer(self):
        with mock.patch.object(config, "_extra", [os.path.join(self.dir, "mine.json")]), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SUB0LLMENGINE_CONFIG", None)
            self.assertEqual(config.writableLayer(), os.path.join(self.dir, "mine.json"))


class TestModel(Tmp):
    def test_plain_file_path(self):
        m = process.model(self.cfg())
        self.assertEqual((m["path"], m["id"], m["exists"], m["facts"]), (self.model, None, True, {}))

    def test_registry_json_fallback_alias_with_file(self):
        root = os.path.join(self.dir, "reg")
        folder = os.path.join(root, "hf", "org", "repo", "abc")
        os.makedirs(folder)
        for f in ("a-Q4_0.gguf", "a-IQ3.gguf"):
            write(os.path.join(folder, f), "")
        reg = {"root": root, "aliases": {"a-q4": "hf/org/repo@abc#a-Q4_0.gguf"},
               "entries": {"hf/org/repo@abc": {"dir": "hf/org/repo/abc", "files": [{"name": "a-Q4_0.gguf"}, {"name": "a-IQ3.gguf"}],
                                               "facts": {"byFile": {"a-Q4_0.gguf": {"blockCount": 65}}}}}}
        write(os.path.join(root, "registry.json"), reg)
        with mock.patch.object(registry, "package", lambda: None), mock.patch.dict(os.environ, {"SUB0_MODEL_REGISTRY": root}):
            m = process.model(self.cfg(model="a-q4"))
        self.assertEqual(m["id"], "hf/org/repo@abc#a-Q4_0.gguf")
        self.assertEqual(os.path.normpath(m["path"]), os.path.normpath(os.path.join(folder, "a-Q4_0.gguf")))
        self.assertEqual(m["facts"], {"blockCount": 65})


class TestCommand(Tmp):
    def test_server_command_flags(self):
        cmd = process.command(self.cfg(ctxCheckpoints=8, cacheRam=4096, extraArgs=["--foo", 1]))
        joined = " ".join(cmd[1:])
        for part in ["-m " + self.model, "--host 127.0.0.1", "-c 16384", "-np 2", "-ngl 99", "-ncmoe 30", "-fa on", "-ctk q8_0",
                     "-ub 512", "-t 8", "--no-mmap", "-kvu", "--alias stub", "--metrics", "-ctxcp 8", "-cram 4096", "--foo 1"]:
            self.assertIn(part, joined)

    def test_kv_unified_per_slot_needs_a_build_with_the_flag(self):
        with self.assertRaises(SystemExit):
            process.command(self.cfg(kvUnifiedPerSlot=8192))
        llamacpp.LlamaCpp._help[self.bin] = "--kv-unified-per-slot N ..."
        self.assertIn("--kv-unified-per-slot 8192", " ".join(process.command(self.cfg(kvUnifiedPerSlot=8192))))

    def test_new_build_uses_load_mode(self):
        llamacpp.LlamaCpp._help[self.bin] = "-lm, --load-mode {none,mmap,mlock,auto}"
        joined = " ".join(process.command(self.cfg(mmap=True)))
        self.assertIn("-lm mmap", joined)
        self.assertNotIn("--no-mmap", joined)


class TestPool(unittest.TestCase):
    def slots(self, *held_busy):
        return [{"id": i, "n_ctx": 1000, "n_prompt_tokens": h, "is_processing": b} for i, (h, b) in enumerate(held_busy)]

    def test_levels(self):
        for used, level in [(690, "ok"), (700, "notice"), (850, "warning"), (950, "critical")]:
            self.assertEqual(process.pool({"ctx": 1000, "kvUnified": True}, self.slots((used, True), (40, False)))["level"], level)

    def test_unified_pool_is_ctx_and_separate_pools_add_up(self):
        sl = self.slots((100, True), (200, False))
        self.assertEqual(process.pool({"ctx": 4096, "kvUnified": True}, sl)["size"], 4096)
        self.assertEqual(process.pool({"ctx": 4096, "kvUnified": False}, sl)["size"], 2000)

    def test_no_slots(self):
        self.assertIsNone(process.pool({"ctx": 1}, []))


class TestEngineDescription(Tmp):
    def serve(self, loading=False):
        handler = type("Stub", (StubServer,), {"loading": loading})
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_not_running(self):
        d = process.info(self.cfg(port=self.freePort()))
        self.assertEqual((d["format"], d["running"], d["startedByThisTool"]), ("sub0llmengine.engine.v1", False, False))

    def freePort(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def test_running_not_started_here(self):
        cfg = self.cfg(port=self.serve())
        d = process.info(cfg)
        self.assertTrue(d["running"])
        self.assertEqual((d["alias"], d["slots"], d["busy"], d["nCtxPerSlot"], d["squadCtx"]), ("stub", 2, 1, 8192, 8192))
        self.assertIsNone(d["matchesConfig"])
        self.assertFalse(d["startedByThisTool"])

    def test_recorded_engine_matches_then_differs(self):
        cfg = self.cfg(port=self.serve(), squadCtx=4096)
        process.record(cfg, ["llama-server"], 123)
        d = process.info(cfg)
        self.assertEqual((d["startedByThisTool"], d["matchesConfig"], d["squadCtx"]), (True, True, 4096))
        self.assertEqual(d["model"]["path"], self.model)
        self.assertTrue(d["build"].startswith("llama.cpp"))
        d = process.info(dict(cfg, ctx=32768, slots=4))
        self.assertFalse(d["matchesConfig"])
        self.assertEqual(d["differences"], {"ctx": [16384, 32768], "slots": [2, 4]})

    def test_start_when_answering_does_not_start_another(self):
        cfg = self.cfg(port=self.serve())
        said = []
        with mock.patch("subprocess.Popen") as popen:
            self.assertEqual(process.start(cfg, say=said.append), 0)
            popen.assert_not_called()
        self.assertIn("not started by this tool", said[0])

    def test_start_refuses_while_a_bench_holds_the_gpu(self):
        me = str(os.getpid())  # a live owner
        write(process.LOCK_FILE, me)
        said = []
        with mock.patch("subprocess.Popen") as popen:
            self.assertEqual(process.start(self.cfg(port=self.freePort()), say=said.append), 2)
            popen.assert_not_called()
        self.assertIn(me, said[0])
        self.assertEqual(process.info(self.cfg(port=self.freePort()))["benchLock"], me)

    def test_lock_of_a_crashed_bench_does_not_block(self):
        write(process.LOCK_FILE, str(deadPid()))
        self.assertIsNone(process.benchLockOwner())

    def test_bench_sets_aside_a_crashed_benchs_lock(self):
        from sub0llmengine import bench
        dead = deadPid()
        write(process.LOCK_FILE, str(dead))
        with mock.patch.object(bench.GpuLock, "path", process.LOCK_FILE), mock.patch.object(bench.activity, "write", lambda **k: None):
            with bench.GpuLock():
                self.assertEqual(open(process.LOCK_FILE).read(), str(os.getpid()))
        self.assertTrue(os.path.exists(process.LOCK_FILE + ".stale-%d" % dead))

    def test_pool_watermark_from_slots(self):
        cfg = self.cfg(port=self.serve(), ctx=8192)
        pl = process.info(cfg)["pool"]
        self.assertEqual((pl["size"], pl["used"], pl["reclaimable"], pl["free"], pl["busySlots"], pl["level"]),
                         (8192, 3000, 1000, 5192, 1, "ok"))

    def test_loading_server_counts_as_starting_and_is_not_started_again(self):
        cfg = self.cfg(port=self.serve(loading=True))
        self.assertEqual(process.health(cfg), "loading")
        self.assertFalse(process.running(cfg))
        d = process.info(cfg)
        self.assertEqual((d["running"], d["loading"]), (False, True))
        with mock.patch("subprocess.Popen") as popen:
            self.assertEqual(process.start(cfg, wait=False, say=lambda m: None), 0)
            popen.assert_not_called()

    def test_stop_with_nothing_running(self):
        self.assertEqual(process.stop(self.cfg(port=self.freePort()), say=lambda m: None), 0)

    def test_stop_refuses_an_engine_it_did_not_start(self):
        self.assertEqual(process.stop(self.cfg(port=self.serve()), say=lambda m: None), 1)


if __name__ == "__main__":
    unittest.main()
