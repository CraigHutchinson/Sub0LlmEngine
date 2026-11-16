"""Named profiles: evidence checks without a GPU (fake binary folder, plain model file)."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from sub0llmengine import profiles
from sub0llmengine.backends import llamacpp


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        open(os.path.join(self.bin, "llama-server" + llamacpp.EXE), "w").close()
        self.model = os.path.join(self.dir, "m.gguf")
        open(self.model, "w").close()
        p = mock.patch.object(profiles, "DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)
        b = mock.patch.object(llamacpp.LlamaCpp, "buildLabel", lambda self, cfg: "llama.cpp b1")
        b.start()
        self.addCleanup(b.stop)

    def write(self, name, evidence):
        with open(os.path.join(self.dir, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"_comment": "test", "binDir": self.bin, "model": self.model, "slots": 4, "ctx": 65536, "_evidence": evidence}, f)

    def test_matching_evidence_is_not_stale(self):
        self.write("good", {"build": "llama.cpp b1", "records": ["2026-01-01T00:00:00"]})
        r = profiles.check("good", base={}, history=[{"ts": "2026-01-01T00:00:00"}])
        self.assertEqual((r["stale"], r["problems"], r["settings"]["slots"]), (False, [], 4))
        self.assertEqual(profiles.names(), ["good"])

    def test_other_build_or_missing_records_is_stale(self):
        self.write("old", {"build": "llama.cpp b0", "records": ["2026-01-01T00:00:00"]})
        r = profiles.check("old", base={}, history=[])
        self.assertTrue(r["stale"])
        self.assertEqual(len(r["problems"]), 2)

    def test_no_evidence_is_stale_and_unknown_profile_exits(self):
        self.write("bare", {})
        self.assertTrue(profiles.check("bare", base={}, history=[])["stale"])
        with self.assertRaises(SystemExit):
            profiles.path("missing")


if __name__ == "__main__":
    unittest.main()
