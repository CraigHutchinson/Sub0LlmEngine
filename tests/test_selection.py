import copy
import unittest

from sub0llmengine.selection import validate


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.params = dict(nCpuMoe=32, ctx=65536, ubatch=512, batch=2048, threads=16,
                           cacheTypeK="q8_0", cacheTypeV="q8_0", flashAttn="on", kvUnified=True,
                           mmap=False, gpuLayers=99)
        self.identity = dict(machine="host", backend="llamacpp", model="model", build="build")
        self.record = dict(self.identity, params=self.params, depth=2048, ntg=128, B=4, outcome="ok", tgTps=100)
        self.profile = dict(schema="sub0llmengine.measured-selection.v1", identity=self.identity,
                            engineConfig=dict(self.params, backend="llamacpp", model="model", slots=4, squadCtx=2176),
                            evidence=dict(depth=2048, concurrency=4, generatedTokens=128),
                            consumerBudget=dict(maxConcurrentRequests=4, maxPromptTokens=2048,
                                                maxOutputTokens=128, maxTotalTokens=2176))

    def receive(self, profile=None, records=None):
        return validate(profile or self.profile, records if records is not None else [self.record], "host", "build")

    def test_receives_exact_point_without_claiming_server_validation(self):
        result = self.receive()
        self.assertEqual(result["engineConfig"], self.profile["engineConfig"])
        self.assertFalse(result["serverValidated"])
        self.assertEqual(result["localPasses"], 1)

    def test_identity_drift_is_rejected(self):
        for key in ("machine", "model", "build", "backend"):
            p = copy.deepcopy(self.profile)
            p["identity"][key] = "other"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.receive(p)

    def test_allocated_context_cannot_expand_consumer_budget(self):
        p = copy.deepcopy(self.profile)
        p["consumerBudget"]["maxPromptTokens"] = 65536
        with self.assertRaises(ValueError):
            self.receive(p)

    def test_knob_changes_or_unconsumed_knobs_are_rejected(self):
        for key, value in (("threads", 8), ("extraArgs", ["--anything"]), ("mmap", True)):
            p = copy.deepcopy(self.profile)
            p["engineConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.receive(p)

    def test_missing_excluded_or_conflicting_evidence_is_rejected(self):
        for records in ([], [dict(self.record, excluded="contended")],
                        [self.record, dict(self.record, outcome="oom")]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                self.receive(records=records)

    def test_malformed_sections_and_workloads_are_rejected(self):
        for key, value in (("identity", []), ("engineConfig", None), ("evidence", "bad")):
            p = copy.deepcopy(self.profile)
            p[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.receive(p)

        for value in (True, 0, -1, 1.5):
            p = copy.deepcopy(self.profile)
            p["evidence"]["concurrency"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.receive(p)

    def test_invalid_throughput_is_not_receiving_evidence(self):
        for value in (None, True, float("nan"), float("inf"), 0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.receive(records=[dict(self.record, tgTps=value)])


if __name__ == "__main__":
    unittest.main()
