import unittest
from unittest import mock

from sub0llmengine import versions


class VersionsTest(unittest.TestCase):
    def test_strata_reports_control_version_and_engine_build(self):
        out = "strata 0.2.20 (build 0.1.66; python 3.12.15 at C:/x/python.exe)"
        with mock.patch.object(versions, "_run", return_value=out):
            self.assertEqual(versions.installed("strata", {"strataBin": "strata"}), ("0.2.20", "engine build 0.1.66"))

    def test_basalt_uses_config_key(self):
        self.assertEqual(versions.installed("basalt", {"basaltVersion": "0.5.6"})[0], "0.5.6")
        self.assertIsNone(versions.installed("basalt", {})[0])

    def test_only_semver_backends_compare(self):
        with mock.patch.object(versions, "_latest", return_value="v0.3.0"), \
             mock.patch.object(versions, "installed", return_value=("0.2.20", "")), \
             mock.patch("sub0llmengine.config.load", return_value={}):
            rows = {r["name"]: r for r in versions.check(["strata", "llamacpp"])}
        self.assertTrue(rows["strata"]["updateAvailable"])
        self.assertFalse(rows["llamacpp"]["updateAvailable"])


if __name__ == "__main__":
    unittest.main()
