"""Platform layer: path mapping, per-platform config layers and process helpers, on whichever OS runs the tests."""
import os
import subprocess
import sys
import unittest
from unittest import mock

from sub0llmengine import config, platform


class TestPaths(unittest.TestCase):
    def test_windows_drive_paths_map_to_wsl_mounts_off_windows(self):
        with mock.patch.object(platform, "IS_WINDOWS", False):
            self.assertEqual(platform.localPath("D:/LlmModels/x.gguf"), "/mnt/d/LlmModels/x.gguf")
            self.assertEqual(platform.localPath("C:" + "\\" + "tools" + "\\" + "bin"), "/mnt/c/tools/bin")
            self.assertEqual(platform.localPath("/opt/llama"), "/opt/llama")
            self.assertEqual(platform.localPath(""), "")

    def test_paths_unchanged_on_windows(self):
        with mock.patch.object(platform, "IS_WINDOWS", True):
            self.assertEqual(platform.localPath("D:/LlmModels"), "D:/LlmModels")

    def test_platform_names(self):
        self.assertEqual(platform.NAMES[0], "windows" if os.name == "nt" else "linux")
        self.assertEqual(platform.EXE, ".exe" if os.name == "nt" else "")


class TestLayers(unittest.TestCase):
    def test_platform_layers_follow_local_and_precede_extra(self):
        names = [os.path.basename(p) for p in config.layers()]
        self.assertEqual(names[:2], ["engine.defaults.json", "engine.local.json"])
        self.assertEqual(names[2:2 + len(platform.NAMES)], ["engine.local.%s.json" % n for n in platform.NAMES])

    def test_writable_layer_is_local_without_extra_layers(self):
        with mock.patch.object(config, "_extra", []), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SUB0LLMENGINE_CONFIG", None)
            self.assertEqual(config.writableLayer(), config.LOCAL)


class TestProcesses(unittest.TestCase):
    def test_alive_and_terminate_a_real_child(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=os.name != "nt")
        try:
            self.assertTrue(platform.alive(p.pid))
            platform.terminate(p.pid)
            p.wait(timeout=20)
            self.assertFalse(platform.alive(p.pid))
        finally:
            if p.poll() is None:
                p.kill()


if __name__ == "__main__":
    unittest.main()
