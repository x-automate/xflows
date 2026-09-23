"""Wave 5 tests: APIGen pipeline helper functions (docs 06 XU-3)."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta

from app.workflows import (
    _APIGEN_CHILD_WORKFLOWS,
    _as_dict,
    _extract_request_text,
    _lint_spec,
    _stage,
    _stage_record,
    _subworkflow_result,
    aggregate_usage,
    node_retry_policy,
    node_timeout,
    parse_payload,
    run_timeout,
)


class NodeRetryPolicyTests(unittest.TestCase):
    def test_defaults(self) -> None:
        policy = node_retry_policy({})
        self.assertEqual(policy.maximum_attempts, 3)
        self.assertEqual(policy.initial_interval, timedelta(milliseconds=1000))
        self.assertEqual(policy.maximum_interval, timedelta(seconds=30))

    def test_custom_retry_block(self) -> None:
        policy = node_retry_policy({"retry": {"attempts": 5, "backoffMs": 250}})
        self.assertEqual(policy.maximum_attempts, 5)
        self.assertEqual(policy.initial_interval, timedelta(milliseconds=250))

    def test_attempts_clamped_to_one(self) -> None:
        policy = node_retry_policy({"retry": {"attempts": 0}})
        self.assertEqual(policy.maximum_attempts, 1)

    def test_invalid_values_fall_back_to_defaults(self) -> None:
        policy = node_retry_policy({"retry": {"attempts": "bad", "backoffMs": "bad"}})
        self.assertEqual(policy.maximum_attempts, 3)
        self.assertEqual(policy.initial_interval, timedelta(milliseconds=1000))

    def test_non_dict_retry_ignored(self) -> None:
        policy = node_retry_policy({"retry": "nope"})
        self.assertEqual(policy.maximum_attempts, 3)


class NodeTimeoutTests(unittest.TestCase):
    def test_default(self) -> None:
        self.assertEqual(node_timeout({}), timedelta(seconds=120))

    def test_custom(self) -> None:
        self.assertEqual(node_timeout({"timeoutS": 30}), timedelta(seconds=30))

    def test_clamped_to_one_second(self) -> None:
        self.assertEqual(node_timeout({"timeoutS": 0.1}), timedelta(seconds=1))

    def test_invalid_falls_back(self) -> None:
        self.assertEqual(node_timeout({"timeoutS": "bad"}), timedelta(seconds=120))


class RunTimeoutTests(unittest.TestCase):
    def test_default(self) -> None:
        self.assertEqual(run_timeout(None), timedelta(seconds=900))

    def test_custom(self) -> None:
        self.assertEqual(run_timeout({"executionTimeoutS": 5}), timedelta(seconds=5))

    def test_capped_at_max(self) -> None:
        self.assertEqual(run_timeout({"executionTimeoutS": 100000}), timedelta(seconds=86400))

    def test_clamped_to_one_second(self) -> None:
        self.assertEqual(run_timeout({"executionTimeoutS": 0}), timedelta(seconds=1))

    def test_invalid_falls_back(self) -> None:
        self.assertEqual(run_timeout({"executionTimeoutS": "bad"}), timedelta(seconds=900))


class AggregateUsageTests(unittest.TestCase):
    def test_mixed_outputs(self) -> None:
        outputs = {
            "a": {"usage": {"input": 10, "output": 20, "total": 30, "costUsd": 0.5}},
            "b": {"usage": {"input": 1, "output": 2, "total": 3, "costUsd": 0.25}},
            "c": {"no_usage_here": True},
            "d": {"usage": "bad"},
        }
        self.assertEqual(
            aggregate_usage(outputs),
            {
                "inputTokens": 11,
                "outputTokens": 22,
                "totalTokens": 33,
                "costEstimateUsd": 0.75,
                "nodes": 2,
            },
        )

    def test_partial_bad_values_are_skipped(self) -> None:
        totals = aggregate_usage({"a": {"usage": {"input": "oops", "output": 5, "total": 5}}})
        self.assertEqual(totals["nodes"], 1)
        self.assertEqual(totals["inputTokens"], 0)
        self.assertEqual(totals["outputTokens"], 0)
        self.assertEqual(totals["totalTokens"], 0)

    def test_empty(self) -> None:
        self.assertEqual(aggregate_usage({})["nodes"], 0)


class StageShapeTests(unittest.TestCase):
    def test_stage(self) -> None:
        stage = _stage("s1", "AgentLoop", prompt="hi", schema={"type": "object"})
        self.assertEqual(stage["id"], "s1")
        self.assertEqual(stage["componentId"], "AgentLoop")
        self.assertEqual(stage["params"], {"prompt": "hi", "schema": {"type": "object"}})

    def test_stage_record(self) -> None:
        record = _stage_record({"id": "s1", "componentId": "Codegen"}, "succeeded", output={"hash": "h"})
        self.assertEqual(
            record,
            {"id": "s1", "componentId": "Codegen", "status": "succeeded", "output": {"hash": "h"}},
        )

    def test_stage_record_missing_fields(self) -> None:
        record = _stage_record({}, "failed")
        self.assertEqual(record, {"id": "", "componentId": "", "status": "failed"})


class ParsePayloadTests(unittest.TestCase):
    def test_json_string_parsed(self) -> None:
        self.assertEqual(parse_payload('{"a": 1}'), {"a": 1})

    def test_non_json_string_unchanged(self) -> None:
        self.assertEqual(parse_payload("not json"), "not json")

    def test_non_string_unchanged(self) -> None:
        self.assertEqual(parse_payload(42), 42)


class AsDictTests(unittest.TestCase):
    def test_dict_passthrough(self) -> None:
        value = {"a": 1}
        self.assertIs(_as_dict(value), value)

    def test_non_dict_becomes_empty(self) -> None:
        self.assertEqual(_as_dict("x"), {})
        self.assertEqual(_as_dict(None), {})
        self.assertEqual(_as_dict([1]), {})


class LintSpecTests(unittest.TestCase):
    def test_empty_spec_has_three_errors(self) -> None:
        errors = _lint_spec({})
        self.assertEqual(
            errors,
            [
                "paths must be a non-empty object",
                "info.title must be a non-empty string",
                "openapi version must be a non-empty string",
            ],
        )

    def test_missing_title_only(self) -> None:
        errors = _lint_spec({"openapi": "3.1.0", "paths": {"/x": {"get": {}}}})
        self.assertEqual(errors, ["info.title must be a non-empty string"])

    def test_valid_spec(self) -> None:
        spec = {"openapi": "3.1.0", "info": {"title": "T"}, "paths": {"/x": {"get": {}}}}
        self.assertEqual(_lint_spec(spec), [])

    def test_blank_values_are_errors(self) -> None:
        errors = _lint_spec({"openapi": "  ", "info": {"title": "  "}, "paths": {}})
        self.assertEqual(len(errors), 3)


class ExtractRequestTextTests(unittest.TestCase):
    def test_none(self) -> None:
        self.assertEqual(_extract_request_text(None), "")

    def test_string_passthrough(self) -> None:
        self.assertEqual(_extract_request_text("hello"), "hello")

    def test_text_key(self) -> None:
        self.assertEqual(_extract_request_text({"text": "t"}), "t")

    def test_value_key(self) -> None:
        self.assertEqual(_extract_request_text({"value": "v"}), "v")

    def test_non_string_text_serialized(self) -> None:
        self.assertEqual(_extract_request_text({"text": {"a": 1}}), '{"a": 1}')

    def test_other_keys_serialized(self) -> None:
        self.assertEqual(_extract_request_text({"other": 1}), '{"other": 1}')

    def test_non_dict_serialized(self) -> None:
        self.assertEqual(_extract_request_text([1, 2]), "[1, 2]")


class SubworkflowResultTests(unittest.TestCase):
    def test_success_wraps_output(self) -> None:
        self.assertEqual(
            _subworkflow_result("n1", "wf1", {"status": "succeeded", "output": {"done": True}}),
            {"value": {"done": True}},
        )

    def test_non_dict_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _subworkflow_result("n1", "wf1", "nope")
        self.assertEqual(str(ctx.exception), "subworkflow node 'n1' ('wf1') did not succeed")

    def test_failed_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            _subworkflow_result("n1", "wf1", {"status": "failed", "output": {"error": "x"}})


class ApigenChildWorkflowsTests(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertEqual(
            _APIGEN_CHILD_WORKFLOWS,
            {
                "apigen.generate": "ApiGenGenerateWorkflow.run",
                "apigen.validate": "ApiGenValidateWorkflow.run",
                "apigen.deploy": "ApiGenDeployWorkflow.run",
            },
        )


if __name__ == "__main__":
    unittest.main()
