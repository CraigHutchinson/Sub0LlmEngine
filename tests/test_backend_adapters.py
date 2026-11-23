import os
import tempfile
import unittest

from sub0llmengine import backends, platform, process


class BackendAdapterTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.strata = os.path.join(self.dir, "strata.cmd")
        self.strata_profile = os.path.join(self.dir, "strata-profile.json")
        self.basalt = os.path.join(self.dir, "basalt.exe")
        self.basalt_config = os.path.join(self.dir, "basalt-config.json")
        for path in (self.strata, self.strata_profile, self.basalt, self.basalt_config):
            with open(path, "w", encoding="utf-8") as f:
                f.write("{}")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def test_strata_command_uses_native_profile_and_serving_overrides(self):
        cfg = {"backend": "strata", "strataBin": self.strata, "strataProfile": self.strata_profile,
               "host": "127.0.0.1", "port": 8123, "slots": 2}
        cmd = backends.get(cfg).serverCommand(cfg, "unused-model")
        joined = " ".join(cmd)
        self.assertIn("serve", joined)
        self.assertIn("--profile", joined)
        self.assertIn(self.strata_profile, joined)
        self.assertIn("--engine strata", joined)
        self.assertIn("--port 8123", joined)
        self.assertIn("--parallel 2", joined)
        if platform.IS_WINDOWS:
            self.assertEqual(os.path.basename(cmd[0]).lower(), os.path.basename(os.environ.get("COMSPEC", "cmd.exe")).lower())
        else:
            self.assertEqual(cmd[0], self.strata)

    def test_basalt_command_uses_native_server_config(self):
        cfg = {"backend": "basalt", "basaltBin": self.basalt, "basaltConfig": self.basalt_config}
        self.assertEqual(backends.get(cfg).serverCommand(cfg, "unused-model"),
                         [self.basalt, "serve", "--config", self.basalt_config])

    def test_missing_native_config_is_reported(self):
        with self.assertRaisesRegex(SystemExit, "basaltConfig"):
            backends.get({"backend": "basalt"}).serverCommand({"basaltBin": self.basalt}, "unused-model")

    def test_native_config_contents_are_part_of_engine_identity(self):
        cfg = {"backend": "basalt", "basaltConfig": self.basalt_config}
        before = process.identity(cfg)["backendConfigFingerprint"]
        with open(self.basalt_config, "w", encoding="utf-8") as f:
            f.write('{"context": 8192}')
        after = process.identity(cfg)["backendConfigFingerprint"]
        self.assertNotEqual(before, after)

    def test_shared_sweep_rejects_incomparable_native_benchmark(self):
        for name in ("strata", "basalt"):
            with self.subTest(backend=name), self.assertRaisesRegex(SystemExit, "shared sweep"):
                backends.get({"backend": name}).benchCommand({}, "", 128, 16, [1])


if __name__ == "__main__":
    unittest.main()


class ModelRequestTest(unittest.TestCase):
    def test_backends_declare_their_formats(self):
        self.assertEqual(backends.get({}).modelFormats(), ["gguf"])
        self.assertEqual(backends.get({"backend": "strata"}).modelFormats(), ["strata", "gguf"])
        self.assertEqual(backends.get({"backend": "basalt"}).modelFormats(), ["basalt"])

    def test_model_name_resolves_in_the_backend_format(self):
        import json
        from sub0llmengine import registry
        pkg = registry.package()
        if pkg is None:
            self.skipTest("Sub0LlmModelRegistry package not available")
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "models"))
            with open(os.path.join(root, "models", "toy.json"), "w") as f:
                json.dump({"name": "toy", "artifacts": [{"format": "basalt", "variant": "P", "source": "hf:o/toy-B#toy.basalt"}]}, f)
            folder = os.path.join(root, "hf", "o", "toy-B", "abc123def456")
            os.makedirs(folder)
            with open(os.path.join(folder, "toy.basalt"), "wb") as f:
                f.write(b"x")
            pkg.Registry(root).newManifest(folder, fmt="basalt", source={"provider": "hf", "repo": "o/toy-B"})
            path, _ = registry.resolve({"registry": root, "backend": "basalt"}, "toy")
            self.assertTrue(path.endswith("toy.basalt"))
            with self.assertRaises(SystemExit) as e:  # llama.cpp cannot load a pack: refused, not substituted
                registry.resolve({"registry": root}, "toy")
            self.assertIn("gguf", str(e.exception))
        finally:
            import shutil
            shutil.rmtree(root)
