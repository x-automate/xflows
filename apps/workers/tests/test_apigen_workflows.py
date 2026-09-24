"""Wave 5 tests: APIGen Temporal workflows (docs 04 §2, 06 XU-3).

Patches the module-level ``workflow`` namespace (the temporalio workflow module
reference) with a fake so the workflow classes run as plain asyncio.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest import mock

from temporalio.exceptions import ActivityError

from app import workflows as app_workflows

workflow_module = app_workflows

VALID_SPEC: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "T"},
    "paths": {"/x": {"get": {}}},
}
_SPEC_HASH = hashlib.sha256(json.dumps(VALID_SPEC, sort_keys=True, default=str).encode("utf-8")).hexdigest()
_UNSET = object()


class ApiGenTestBase(unittest.IsolatedAsyncioTestCase):
    FIXED_NOW = datetime(2026, 9, 22, 12, 0, 0)

    def setUp(self) -> None:
        self.activity_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.approval_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.child_calls: list[tuple[str, list[Any], dict[str, Any]]] = []
        self.complete_run_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.load_workflow_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.load_workflow_payload: dict[str, Any] = {}

    def install(self, attr: str, repl: Any) -> None:
        patcher = mock.patch.object(workflow_module, attr, repl)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _noop_activity_handler(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        raise AssertionError(f"unexpected activity '{name}' stage={args[0]!r}")

    async def _noop_child_handler(self, name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        raise AssertionError(f"unexpected child workflow '{name}'")

    def install_activity_fake(self, handler: Any) -> None:
        async def fake_activity(name: str, *args: Any, **kwargs: Any) -> Any:
            # Activities are invoked as execute_activity(name, args=[...]) (temporalio 1.8.0).
            if "args" in kwargs:
                call_args = list(kwargs.pop("args"))
            else:
                call_args = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
            if name == "xflows.complete_run":
                self.complete_run_calls.append((name, call_args, kwargs))
                return {"value": {"id": call_args[0]}}
            if name == "xflows.prepare_approval":
                self.approval_calls.append((name, call_args, kwargs))
                return {"signalTimeoutS": 5}
            if name == "xflows.record_approval":
                self.approval_calls.append((name, call_args, kwargs))
                return {"value": True}
            if name == "xflows.load_workflow":
                self.load_workflow_calls.append((name, call_args, kwargs))
                return self.load_workflow_payload.get(call_args[0])
            self.activity_calls.append((name, call_args, kwargs))
            return await handler(name, call_args, kwargs)

        self._activity_fake = fake_activity

    def install_child_fake(self, handler: Any) -> None:
        async def fake_child(name: str, *args: Any, **kwargs: Any) -> Any:
            call_args = kwargs.pop("args", args)
            self.child_calls.append((name, call_args, kwargs))
            return await handler(name, call_args, kwargs)

        self._child_fake = fake_child

    def install_wait_and_now(self) -> None:
        async def fake_wait(fn: Any) -> None:
            while not fn():
                await asyncio.sleep(0)

        self._wait_fake = fake_wait

    def install_pipeline(self, activity_handler: Any = None, child_handler: Any = None) -> None:
        self.install_activity_fake(activity_handler or self._noop_activity_handler)
        self.install_child_fake(child_handler or self._noop_child_handler)
        self.install_wait_and_now()
        namespace = SimpleNamespace(
            execute_activity=self._activity_fake,
            execute_child_workflow=self._child_fake,
            wait_condition=self._wait_fake,
            now=lambda: self.FIXED_NOW,
        )
        self.install("workflow", namespace)

    def make_activity_handler(
        self,
        *,
        classify_result: dict[str, Any] | None = None,
        clarify_results: list[dict[str, Any]] | None = None,
        spec_results: list[dict[str, Any]] | None = None,
        spec_activity_errors: tuple[int, ...] = (),
        codegen_hashes: tuple[str, ...] = ("abc123",),
        policy_result: dict[str, Any] | None = None,
        lambda_result: Any = _UNSET,
    ) -> Any:
        classify_result = classify_result if classify_result is not None else {"value": {"decision": "accept"}}
        clarify_results = clarify_results if clarify_results is not None else [{"value": {"action": "ready"}}]
        spec_results = spec_results if spec_results is not None else [{"value": dict(VALID_SPEC)}]
        policy_result = policy_result if policy_result is not None else {"value": {"allowed": True}}
        codegen_index = {"n": 0}

        async def handler(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            stage = args[0]
            component_id = str(stage.get("componentId", ""))
            stage_id = str(stage.get("id", ""))
            if component_id == "AgentLoop":
                if stage_id == "classify":
                    return classify_result
                if stage_id.startswith("clarify-"):
                    index = min(int(stage_id.split("-")[1]) - 1, len(clarify_results) - 1)
                    return clarify_results[index]
                if stage_id.startswith("spec-"):
                    spec_round = int(stage_id.split("-")[1])
                    if spec_round in spec_activity_errors:
                        raise self._activity_error("schema validation failed")
                    index = min(spec_round - 1, len(spec_results) - 1)
                    return spec_results[index]
                raise AssertionError(f"unexpected AgentLoop stage '{stage_id}'")
            if component_id == "SchemaValidate":
                return {"value": args[1].get("value")}
            if component_id == "Codegen":
                index = min(codegen_index["n"], len(codegen_hashes) - 1)
                codegen_index["n"] += 1
                return {"value": {"hash": codegen_hashes[index]}}
            if component_id == "XWSIAMEvaluate":
                return policy_result
            if component_id == "XWSLambdaInvoke":
                if lambda_result is _UNSET:
                    return {"value": {"ok": True}}
                return lambda_result
            raise AssertionError(f"unexpected activity component '{component_id}'")

        return handler

    def make_child_handler(
        self,
        *,
        validate_results: list[dict[str, Any]] | None = None,
        deploy_result: dict[str, Any] | None = None,
        deploy_error: Exception | None = None,
    ) -> Any:
        validate_queue = list(validate_results) if validate_results else []

        async def handler(name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
            if name == "ApiGenValidateWorkflow.run":
                if validate_queue:
                    return validate_queue.pop(0)
                return {"status": "succeeded", "output": {"ok": True}}
            if name == "ApiGenDeployWorkflow.run":
                if deploy_error is not None:
                    raise deploy_error
                if deploy_result is not None:
                    return deploy_result
                return {"status": "succeeded", "output": {"manifest": {"url": "https://x"}}}
            if name == "XFlowsWorkflow.run":
                return {"status": "succeeded", "output": {"done": True}}
            raise AssertionError(f"unexpected child workflow '{name}'")

        return handler

    def make_generate_workflow(
        self,
        decision: str = "approve",
        reviewer: str = "alice",
    ) -> app_workflows.ApiGenGenerateWorkflow:
        workflow = app_workflows.ApiGenGenerateWorkflow()
        workflow._approvals.record("review", decision, {"reviewer": reviewer})
        return workflow

    async def run_generate(
        self,
        user_input: Any,
        runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.make_generate_workflow().run(user_input, "run1", "trace1", runtime)

    def exec_ids(self) -> list[str]:
        return [str(call[1][0].get("id", "")) for call in self.activity_calls]

    def stage_call(self, component_id: str) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        for call in self.activity_calls:
            if str(call[1][0].get("componentId", "")) == component_id:
                return call[1][0], call[1][1].get("value"), call[2]
        raise AssertionError(f"no activity stage call for component '{component_id}'")

    def completed_stage(self, stage_id: str) -> dict[str, Any]:
        assert self.complete_run_calls, "no complete_run activity was called"
        payload = self.complete_run_calls[-1][1][3]
        matches = [stage for stage in payload.get("stages", []) if str(stage.get("id", "")) == stage_id]
        if not matches:
            raise AssertionError(f"no stage record for '{stage_id}'")
        return matches[-1]

    @staticmethod
    def _activity_error(message: str) -> ActivityError:
        return ActivityError(
            message,
            scheduled_event_id=1,
            started_event_id=2,
            identity="test",
            activity_type=None,
            activity_id=None,
            retry_state=None,
        )


class ApiGenGenerateTests(ApiGenTestBase):
    async def test_happy_path_generates_and_deploys(self) -> None:
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "succeeded")
        output = result["output"]
        self.assertEqual(output["bundleHash"], "abc123")
        self.assertEqual(output["manifest"], {"url": "https://x"})
        self.assertEqual(output["spec"], VALID_SPEC)
        self.assertIs(output["registrationDeferred"], True)

        self.assertEqual(
            self.exec_ids(),
            [
                "classify",
                "classify-validate",
                "clarify-1",
                "clarify-validate-1",
                "spec-1",
                "spec-validate-1",
                "codegen",
                "policy",
            ],
        )

        stage, value, kwargs = self.stage_call("AgentLoop")
        self.assertEqual(stage["id"], "classify")
        self.assertEqual(value, "Build an API")
        self.assertEqual(kwargs["schedule_to_close_timeout"], timedelta(seconds=600))
        self.assertEqual(kwargs["retry_policy"].maximum_attempts, 2)

        codegen_stage, codegen_value, codegen_kwargs = self.stage_call("Codegen")
        self.assertEqual(codegen_stage["id"], "codegen")
        self.assertEqual(codegen_value, VALID_SPEC)
        self.assertEqual(codegen_kwargs["schedule_to_close_timeout"], timedelta(seconds=300))

        policy_stage, policy_value, policy_kwargs = self.stage_call("XWSIAMEvaluate")
        self.assertEqual(policy_stage["id"], "policy")
        self.assertEqual(policy_stage["params"]["action"], "apigen:deploy")
        self.assertEqual(policy_stage["params"]["resource"], "bundle:abc123")
        self.assertEqual(policy_stage["params"]["principal"], "apigen-pipeline")
        self.assertEqual(policy_value, {"decision": "approve"})
        self.assertEqual(policy_kwargs["schedule_to_close_timeout"], timedelta(seconds=60))
        self.assertEqual(policy_kwargs["retry_policy"].maximum_attempts, 1)

        records = [call for call in self.approval_calls if call[0] == "xflows.record_approval"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1][2], "review")
        self.assertEqual(records[0][1][3]["decision"], "approved")

        self.assertEqual(self.child_calls[0][0], "ApiGenValidateWorkflow.run")
        self.assertEqual(self.child_calls[0][1][0], {"spec": VALID_SPEC, "bundle": {"hash": "abc123"}})
        self.assertEqual(self.child_calls[0][2]["id"], "run1:validate-1")

        deploy_name, deploy_args, deploy_kwargs = self.child_calls[-1]
        self.assertEqual(deploy_name, "ApiGenDeployWorkflow.run")
        self.assertEqual(set(deploy_args[0].keys()), {"spec", "bundle", "bundleHash", "secretBindings"})
        self.assertEqual(deploy_args[0]["secretBindings"], {})
        self.assertEqual(deploy_kwargs["id"], "run1:deploy")

        self.assertEqual(self.completed_stage("review")["status"], "succeeded")

    async def test_classify_reject_ends_run(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(
                classify_result={"value": {"decision": "clarify", "reason": "unclear", "missing": ["auth"]}}
            )
        )

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["output"]["reason"], "unclear")
        self.assertEqual(result["output"]["missing"], ["auth"])
        self.assertEqual(self.exec_ids(), ["classify", "classify-validate"])
        record = self.completed_stage("classify")
        self.assertEqual(record["status"], "rejected")
        self.assertEqual(record["reason"], "unclear")

    async def test_clarify_rounds_exhausted_needs_input(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(clarify_results=[{"value": {"action": "ask", "questions": ["Which auth?"]}}])
        )

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["output"]["reason"], "clarify rounds exhausted")
        self.assertEqual(result["output"]["questions"], "Which auth?")
        self.assertEqual(len(self.activity_calls), 12)
        self.assertEqual(self.completed_stage("clarify-5")["status"], "escalated")

    async def test_spec_lint_rounds_exhausted_fails(self) -> None:
        self.install_pipeline(self.make_activity_handler(spec_results=[{"value": {"openapi": "2.0"}}]))

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["output"]["error"], "spec generation failed")
        self.assertEqual(len(self.activity_calls), 14)
        self.assertNotIn("codegen", self.exec_ids())
        self.assertEqual(self.completed_stage("spec-validate-5")["status"], "invalid")
        self.assertEqual(self.child_calls, [])

    async def test_spec_generation_recovers_after_activity_error(self) -> None:
        self.install_pipeline(self.make_activity_handler(spec_activity_errors=(1,)), self.make_child_handler())

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(
            self.exec_ids(),
            [
                "classify",
                "classify-validate",
                "clarify-1",
                "clarify-validate-1",
                "spec-1",
                "spec-2",
                "spec-validate-2",
                "codegen",
                "policy",
            ],
        )
        record = self.completed_stage("spec-1")
        self.assertEqual(record["status"], "invalid")
        self.assertEqual(record["error"], "schema validation failed")
        self.assertEqual(record["componentId"], "AgentLoop")

    async def test_review_request_changes_rejects_run(self) -> None:
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())
        workflow = self.make_generate_workflow(decision="request_changes")

        result = await workflow.run("Build an API", "run1", "trace1", None)

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["output"]["review"]["decision"], "request_changes")
        self.assertEqual(len(self.activity_calls), 7)
        self.assertEqual([call[0] for call in self.child_calls], ["ApiGenValidateWorkflow.run"])

    async def test_policy_deny_rejects_run(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(policy_result={"value": {"allowed": False}}),
            self.make_child_handler(),
        )

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["output"]["policy"], {"allowed": False})
        self.assertEqual(len(self.activity_calls), 8)
        self.assertEqual([call[0] for call in self.child_calls], ["ApiGenValidateWorkflow.run"])

    async def test_repair_loop_redeploys_valid_bundle(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(codegen_hashes=("h1", "h2", "h3")),
            self.make_child_handler(
                validate_results=[
                    {"status": "failed", "output": {"error": "e1"}},
                    {"status": "failed", "output": {"error": "e2"}},
                ]
            ),
        )

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(
            [call[1][0]["id"] for call in self.activity_calls if call[1][0]["componentId"] == "Codegen"],
            ["codegen", "repair-1", "repair-2"],
        )
        self.assertEqual(
            [call[2]["id"] for call in self.child_calls if call[0] == "ApiGenValidateWorkflow.run"],
            ["run1:validate-1", "run1:validate-2", "run1:validate-3"],
        )
        self.assertEqual(self.child_calls[-1][1][0]["bundleHash"], "h3")
        self.assertEqual(result["output"]["bundleHash"], "h3")

    async def test_repair_rounds_exhausted_fails(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(codegen_hashes=("c1", "c2", "c3")),
            self.make_child_handler(
                validate_results=[
                    {"status": "failed", "output": {"error": "e1"}},
                    {"status": "failed", "output": {"error": "e2"}},
                    {"status": "failed", "output": {"error": "e3"}},
                ]
            ),
        )

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [call[1][0]["id"] for call in self.activity_calls if call[1][0]["componentId"] == "Codegen"],
            ["codegen", "repair-1", "repair-2", "repair-3"],
        )
        self.assertEqual(
            [call[2]["id"] for call in self.child_calls if call[0] == "ApiGenValidateWorkflow.run"],
            ["run1:validate-1", "run1:validate-2", "run1:validate-3"],
        )
        self.assertEqual(result["output"]["validation"], {"error": "e3"})
        self.assertEqual(result["output"]["error"], "bundle validation failed after repair rounds")
        self.assertEqual([call for call in self.approval_calls if call[0] == "xflows.record_approval"], [])
        self.assertEqual(
            [call[0] for call in self.child_calls],
            ["ApiGenValidateWorkflow.run"] * 3,
        )

    async def test_runtime_config_flows_to_policy_and_deploy(self) -> None:
        runtime = {"principal": "alice", "sandboxRef": "arn:sb", "liveRef": "arn:lv", "other": "x"}
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())

        result = await self.run_generate("Build an API", runtime=runtime)

        self.assertEqual(result["status"], "succeeded")
        policy_stage, _, _ = self.stage_call("XWSIAMEvaluate")
        self.assertEqual(policy_stage["params"]["principal"], "alice")
        self.assertEqual(
            self.child_calls[-1][1][0]["secretBindings"],
            {"sandbox": "arn:sb", "live": "arn:lv"},
        )

    async def test_deploy_child_failure_fails_run(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(),
            self.make_child_handler(deploy_error=ValueError("boom")),
        )

        result = await self.run_generate("Build an API")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["output"]["error"], "deploy failed: boom")


class ApiGenValidateTests(ApiGenTestBase):
    async def test_validate_success(self) -> None:
        self.install_pipeline(self.make_activity_handler())

        result = await app_workflows.ApiGenValidateWorkflow().run(
            {"bundleHash": "h1"}, "run1", "trace1", None
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["output"], {"ok": True})
        stage, value, kwargs = self.stage_call("XWSLambdaInvoke")
        self.assertEqual(stage["id"], "validate")
        self.assertEqual(stage["params"]["functionName"], "apigen-bundle-validator")
        self.assertEqual(stage["params"]["bundleHash"], "h1")
        self.assertEqual(value, {"bundleHash": "h1"})
        self.assertEqual(kwargs["schedule_to_close_timeout"], timedelta(seconds=600))
        self.assertEqual(kwargs["retry_policy"].maximum_attempts, 1)
        self.assertEqual(self.complete_run_calls, [])

    async def test_validate_requires_bundle_hash(self) -> None:
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())

        result = await app_workflows.ApiGenValidateWorkflow().run("nope", "run1", "trace1", None)

        self.assertEqual(
            result,
            {"status": "failed", "output": {"error": "bundle hash is required for validation"}},
        )
        self.assertEqual(self.activity_calls, [])

    async def test_validate_wraps_raw_lambda_result(self) -> None:
        self.install_pipeline(self.make_activity_handler(lambda_result={"value": "raw text"}))

        result = await app_workflows.ApiGenValidateWorkflow().run(
            {"bundleHash": "h1"}, "run1", "trace1", None
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["output"], {"result": "raw text"})


class ApiGenDeployTests(ApiGenTestBase):
    async def test_deploy_success_builds_manifest(self) -> None:
        self.install_pipeline(self.make_activity_handler())

        result = await app_workflows.ApiGenDeployWorkflow().run(
            {"bundleHash": "h1", "spec": dict(VALID_SPEC)}, "run1", "trace1", None
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(
            result["output"]["manifest"],
            {
                "bundleHash": "h1",
                "specHash": _SPEC_HASH,
                "aliases": {"sandbox": "sandbox:h1", "live": "live:h1"},
                "deployedAt": "2026-09-22T12:00:00",
            },
        )
        self.assertEqual(result["output"]["deploy"], {"ok": True})
        stage, value, kwargs = self.stage_call("XWSLambdaInvoke")
        self.assertEqual(stage["id"], "deploy")
        self.assertEqual(stage["params"]["functionName"], "apigen-deployer")
        self.assertNotIn("secretBindings", stage["params"])
        self.assertEqual(value, {"bundleHash": "h1", "secretBindings": {}})
        self.assertEqual(kwargs["schedule_to_close_timeout"], timedelta(seconds=300))
        self.assertEqual(kwargs["retry_policy"].maximum_attempts, 1)

    async def test_deploy_lambda_aliases_override(self) -> None:
        self.install_pipeline(
            self.make_activity_handler(lambda_result={"value": {"aliases": {"sandbox": "s1", "live": "l1"}}})
        )

        result = await app_workflows.ApiGenDeployWorkflow().run(
            {"bundleHash": "h1", "spec": dict(VALID_SPEC)}, "run1", "trace1", None
        )

        self.assertEqual(result["output"]["manifest"]["aliases"], {"sandbox": "s1", "live": "l1"})
        self.assertEqual(result["output"]["deploy"], {"aliases": {"sandbox": "s1", "live": "l1"}})

    async def test_deploy_requires_bundle_hash(self) -> None:
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())

        result = await app_workflows.ApiGenDeployWorkflow().run({}, "run1", "trace1", None)

        self.assertEqual(
            result,
            {"status": "failed", "output": {"error": "bundle hash is required for deployment"}},
        )
        self.assertEqual(self.activity_calls, [])

    async def test_deploy_runtime_refs_become_secret_bindings(self) -> None:
        self.install_pipeline(self.make_activity_handler())

        result = await app_workflows.ApiGenDeployWorkflow().run(
            {"bundleHash": "h1", "spec": dict(VALID_SPEC)},
            "run1",
            "trace1",
            {"sandboxRef": "arn:sb", "liveRef": "arn:lv"},
        )

        self.assertEqual(result["status"], "succeeded")
        stage, value, _ = self.stage_call("XWSLambdaInvoke")
        self.assertEqual(stage["params"]["secretBindings"], {"sandbox": "arn:sb", "live": "arn:lv"})
        self.assertEqual(value["secretBindings"], {"sandbox": "arn:sb", "live": "arn:lv"})


if __name__ == "__main__":
    unittest.main()
