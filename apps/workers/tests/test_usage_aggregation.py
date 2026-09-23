from __future__ import annotations

import unittest

from app.workflows import aggregate_usage


class AggregateUsageTests(unittest.TestCase):
    def test_sums_usage_across_nodes(self) -> None:
        outputs = {
            "a": {"value": "x", "usage": {"input": 100, "output": 20, "total": 120, "costUsd": 0.0003}},
            "b": {"value": "y", "usage": {"input": 50, "output": 10, "total": 60, "costUsd": 0.001}},
            "c": {"value": "no usage"},
        }
        totals = aggregate_usage(outputs)
        self.assertEqual(totals["inputTokens"], 150)
        self.assertEqual(totals["outputTokens"], 30)
        self.assertEqual(totals["totalTokens"], 180)
        self.assertEqual(totals["nodes"], 2)
        self.assertAlmostEqual(totals["costEstimateUsd"], 0.0013)

    def test_empty_outputs(self) -> None:
        self.assertEqual(aggregate_usage({})["nodes"], 0)
        self.assertEqual(aggregate_usage({"a": {"value": "x"}})["nodes"], 0)

    def test_malformed_usage_ignored(self) -> None:
        totals = aggregate_usage({"a": {"usage": {"input": "bad", "output": None, "total": "x"}}})
        self.assertEqual(totals["nodes"], 1)
        self.assertEqual(totals["totalTokens"], 0)


if __name__ == "__main__":
    unittest.main()
