import unittest

from sub0llmengine import axes, backends, config


class AxesTest(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(config.load(), backend="llamacpp")
        self.d = axes.describe(self.cfg)

    def test_identity_knobs_are_the_measured_params(self):
        self.assertEqual(set(self.d["identity"]), set(config.PARAM_KEYS))

    def test_every_axis_is_moved_by_some_knob(self):
        self.assertEqual([a["id"] for a in self.d["axes"]], ["speed", "context", "concurrency", "prefill"])
        for a in self.d["axes"]:
            self.assertTrue(a["drivenBy"], a["id"])

    def test_knobs_have_a_change_class_and_load_knobs_a_transfer_status(self):
        for k in self.d["knobs"]:
            self.assertIn(k["change"], ("load", "request"))
            if k["change"] == "load":
                self.assertIn(k["transfer"], ("kept", "restored-not-reused", "lost", "unmeasured"))

    def test_server_flags_match_the_command(self):
        flags = {k["flag"] for k in self.d["knobs"] if k.get("flag")}
        for f in ("-c", "-np", "-ub", "-b", "-ncmoe", "-ctk", "-ctv", "-fa", "-ngl", "-t"):
            self.assertIn(f, flags)

    def test_diff_names_changed_knobs_with_their_class(self):
        knobs = backends.get(self.cfg).knobs()
        d = axes.diff(knobs, dict(ctx=32768, ubatch=2048), dict(ctx=106496, ubatch=2048))
        self.assertEqual(d, {"ctx": {"change": "load", "before": 32768, "after": 106496}})

    def test_transfer_findings_worst_verdict_wins_per_model(self):
        rec = lambda changed, **kw: dict(dict(model="m", changed={c: {} for c in changed}, restored=True, identical=True, reused=True), **kw)
        found = axes.transferFindings([
            rec(["ctx", "slots"]),
            rec(["ubatch"], reused=False),
            rec(["cacheTypeK"], restored=False),
            rec(["ctx"], model="other", restored=False),
        ], "m")
        self.assertEqual(found, {"ctx": "kept", "slots": "kept", "ubatch": "restored-not-reused", "cacheTypeK": "lost"})


    def test_newest_build_wins_across_builds(self):
        old = dict(model="m", build="b1", time="2026-11-16T10:00", changed={"ctx": {}}, restored=True, identical=True, reused=False)
        new = dict(old, build="b2", time="2026-11-16T12:00", reused=True)
        self.assertEqual(axes.transferFindings([new, old], "m"), {"ctx": "kept"})
        self.assertEqual(axes.transferFindings([old, new], "m", byBuild=True), {"b1": {"ctx": "restored-not-reused"}, "b2": {"ctx": "kept"}})


if __name__ == "__main__":
    unittest.main()
