from __future__ import annotations

import unittest
from datetime import timedelta

from temporalio.common import RetryPolicy

from app.workflows import node_retry_policy, node_timeout, run_timeout


class NodePolicyTests(unittest.TestCase):
    def test_defaults(self) -> None:
        policy = node_retry_policy({})
        self.assertEqual(policy.maximum_attempts, 3)
        self.assertEqual(policy.initial_interval.total_seconds() * 1000, 1000)
        self.assertEqual(node_timeout({}), timedelta(seconds=120))
        self.assertEqual(run_timeout({}), timedelta(seconds=900))

    def test_node_overrides(self) -> None:
        node = {"retry": {"attempts": 5, "backoffMs": 250}, "timeoutS": 30}
        policy = node_retry_policy(node)
        self.assertEqual(policy.maximum_attempts, 5)
        self.assertEqual(policy.initial_interval.total_seconds() * 1000, 250)
        self.assertEqual(node_timeout(node), timedelta(seconds=30))
        self.assertEqual(run_timeout({"executionTimeoutS": 60}), timedelta(seconds=60))

    def test_invalid_values_fall_back(self) -> None:
        policy = node_retry_policy({"retry": {"attempts": "many", "backoffMs": -5}})
        self.assertEqual(policy.maximum_attempts, 3)
        self.assertEqual(policy.initial_interval.total_seconds() * 1000, 0)
        self.assertEqual(node_timeout({"timeoutS": "soon"}), timedelta(seconds=120))
        self.assertEqual(node_timeout({"timeoutS": 0}), timedelta(seconds=1))
        self.assertEqual(run_timeout({"executionTimeoutS": 999999}), timedelta(seconds=86400))

    def test_policy_types(self) -> None:
        self.assertIsInstance(node_retry_policy({}), RetryPolicy)


if __name__ == "__main__":
    unittest.main()
