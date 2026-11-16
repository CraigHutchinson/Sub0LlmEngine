import unittest

from sub0llmengine import bench


def rec(ts, n, b, outcome, ctx=65536, depth=2048):
    return {"ts": ts, "model": "m", "params": {"nCpuMoe": n, "ctx": ctx}, "depth": depth, "B": b, "outcome": outcome}


class Healing(unittest.TestCase):
    def test_two_later_successes_erase_a_failure(self):
        rs = [rec("t1", 30, 2, "oom"), rec("t2", 30, 2, "ok"), rec("t3", 30, 4, "ok")]
        self.assertEqual(bench.superseded(rs), {bench.recKey(rs[0])})
        self.assertEqual(len(bench.effective(rs)), 2)

    def test_one_later_success_only_contradicts(self):
        rs = [rec("t1", 30, 2, "oom"), rec("t2", 30, 2, "ok")]
        self.assertEqual(bench.superseded(rs), set())
        self.assertEqual(bench.outliers(rs, "m")[(bench.paramsKey(rs[0]["params"]), 2048, 2)]["kind"], "contradiction")

    def test_earlier_successes_do_not_erase(self):
        rs = [rec("t1", 30, 2, "ok"), rec("t2", 30, 4, "ok"), rec("t3", 30, 2, "oom")]
        self.assertEqual(bench.superseded(rs), set())

    def test_lighter_successes_do_not_erase(self):
        rs = [rec("t1", 29, 4, "oom"), rec("t2", 30, 4, "ok"), rec("t3", 31, 4, "ok")]
        self.assertEqual(bench.superseded(rs), set())

    def test_erased_failure_no_longer_infers(self):
        rs = [rec("t1", 30, 1, "oom"), rec("t2", 30, 8, "ok"), rec("t3", 30, 8, "ok")]
        self.assertEqual(bench.predict({"nCpuMoe": 29, "ctx": 65536}, 2048, [1], "m", bench.effective(rs)), None)
        self.assertEqual(bench.predict({"nCpuMoe": 29, "ctx": 65536}, 2048, [1], "m", rs), "oom")


class EdgeProbes(unittest.TestCase):
    spec = {"axes": {"nCpuMoe": [28, 29, 30], "B": [1, 2, 4]}, "depth": [2048]}

    def cell(self, n, b):
        return ({"nCpuMoe": n, "ctx": 65536}, 2048, b)

    def ok(self, n, b):
        p, d, bb = self.cell(n, b)
        return (bench.paramsKey(p), d, bb)

    def test_inferred_cell_beside_a_working_one_is_probed(self):
        cells = [self.cell(29, 2), self.cell(28, 2), self.cell(28, 4)]
        probes = bench.edgeProbes(self.spec, cells, {self.ok(30, 2), self.ok(29, 1)})
        self.assertEqual([(g["params"]["nCpuMoe"], g["B"]) for g in probes], [(29, [2])])

    def test_nothing_beside_working_cells(self):
        self.assertEqual(bench.edgeProbes(self.spec, [self.cell(28, 4)], {self.ok(30, 1)}), [])


if __name__ == "__main__":
    unittest.main()
