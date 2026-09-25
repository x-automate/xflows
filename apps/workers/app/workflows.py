from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporalio.exceptions import ActivityError

    from xflows_engine import NodeGraphRunner, normalize_workflow_graph

    from .approval import DEFAULT_SIGNAL_TIMEOUT_S, ApprovalGate
    from .models import WorkflowDefinition

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_MS = 1000
DEFAULT_NODE_TIMEOUT_S = 120
DEFAULT_RUN_TIMEOUT_S = 900
MAX_RUN_TIMEOUT_S = 86_400

MAX_CLARIFY_ROUNDS = 5
MAX_REPAIR_ROUNDS = 3


def node_retry_policy(node: dict[str, Any]):
    from temporalio.common import RetryPolicy

    retry = node.get("retry") if isinstance(node.get("retry"), dict) else {}
    attempts = retry.get("attempts", DEFAULT_ATTEMPTS)
    try:
        attempts = max(1, int(attempts))
    except (TypeError, ValueError):
        attempts = DEFAULT_ATTEMPTS
    backoff_ms = retry.get("backoffMs", DEFAULT_BACKOFF_MS)
    try:
        backoff_ms = max(0.0, float(backoff_ms))
    except (TypeError, ValueError):
        backoff_ms = float(DEFAULT_BACKOFF_MS)
    return RetryPolicy(
        initial_interval=timedelta(milliseconds=backoff_ms),
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=attempts,
    )


def node_timeout(node: dict[str, Any]) -> timedelta:
    try:
        seconds = float(node.get("timeoutS", DEFAULT_NODE_TIMEOUT_S))
    except (TypeError, ValueError):
        seconds = float(DEFAULT_NODE_TIMEOUT_S)
    return timedelta(seconds=max(1.0, seconds))


def run_timeout(runtime_config: dict[str, Any] | None) -> timedelta:
    config = runtime_config or {}
    try:
        seconds = float(config.get("executionTimeoutS", DEFAULT_RUN_TIMEOUT_S))
    except (TypeError, ValueError):
        seconds = float(DEFAULT_RUN_TIMEOUT_S)
    return timedelta(seconds=max(1.0, min(seconds, MAX_RUN_TIMEOUT_S)))


def aggregate_usage(outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    totals = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "costEstimateUsd": 0.0, "nodes": 0}
    for result in outputs.values():
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
        if not usage:
            continue
        totals["nodes"] += 1
        try:
            totals["inputTokens"] += int(usage.get("input") or 0)
            totals["outputTokens"] += int(usage.get("output") or 0)
            totals["totalTokens"] += int(usage.get("total") or 0)
            totals["costEstimateUsd"] = round(totals["costEstimateUsd"] + float(usage.get("costUsd") or 0.0), 6)
        except (TypeError, ValueError):
            continue
    return totals


def _stage(stage_id: str, component_id: str, **params: Any) -> dict[str, Any]:
    return {"id": stage_id, "componentId": component_id, "params": dict(params)}


def _stage_record(stage: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
    record = {"id": stage.get("id", ""), "componentId": stage.get("componentId", ""), "status": status}
    record.update(extra)
    return record


async def _run_stage(
    run_id: str,
    trace_id: str,
    stage: dict[str, Any],
    input_value: Any,
    runtime_config: dict[str, Any] | None,
    *,
    timeout_s: float = 600.0,
    attempts: int = 2,
) -> dict[str, Any]:
    return await workflow.execute_activity(
        "xflows.execute_node",
        args=[stage, {"value": input_value}, run_id, trace_id, runtime_config or {}],
        schedule_to_close_timeout=timedelta(seconds=timeout_s),
        retry_policy=node_retry_policy({"retry": {"attempts": attempts}}),
    )


async def _finish(
    run_id: str,
    trace_id: str,
    status: str,
    payload: dict[str, Any],
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    payload["stages"] = stages
    await workflow.execute_activity(
        "xflows.complete_run",
        args=[run_id, trace_id, status, payload],
        schedule_to_close_timeout=timedelta(seconds=30),
    )
    return {"status": status, "output": payload}


def parse_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _lint_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        errors.append("paths must be a non-empty object")
    info = spec.get("info")
    if not isinstance(info, dict) or not str(info.get("title", "")).strip():
        errors.append("info.title must be a non-empty string")
    if not str(spec.get("openapi", "")).strip():
        errors.append("openapi version must be a non-empty string")
    return errors


def _extract_request_text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        for key in ("text", "value"):
            inner = body.get(key)
            if isinstance(inner, str):
                return inner
            if inner is not None and not isinstance(inner, str):
                return json.dumps(inner, default=str)
        return json.dumps(body, default=str)
    return json.dumps(body, default=str)


CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason"],
    "properties": {
        "decision": {"type": "string", "enum": ["accept", "reject"]},
        "reason": {"type": "string"},
        "missing": {"type": "array", "items": {"type": "string"}},
    },
}

CLARIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "requirements"],
    "properties": {
        "action": {"type": "string", "enum": ["clarify", "ready"]},
        "requirements": {"type": "object"},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
}

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["openapi", "info", "paths"],
    "properties": {
        "openapi": {"type": "string"},
        "info": {"type": "object"},
        "paths": {"type": "object"},
        "components": {"type": "object"},
    },
}

_CLASSIFY_SYSTEM_PROMPT = (
    "You classify API-generation requests (schema apigen.classification.v1). "
    "Accept only requests that describe a concrete API surface. Respond with a single "
    "JSON envelope of the form {\"action\": \"final\", \"output\": {\"decision\": \"accept\"|\"reject\", "
    "\"reason\": \"...\", \"missing\": [\"...\"]}} and nothing else."
)

_CLARIFY_SYSTEM_PROMPT = (
    "You elicit API requirements (schema apigen.requirements.v1). Respond with a single "
    "JSON envelope of the form {\"action\": \"final\", \"output\": {\"action\": \"clarify\"|\"ready\", "
    "\"requirements\": {...}, \"questions\": [\"...\"]}} and nothing else. Use action clarify while "
    "key resources, operations, or auth expectations are still unknown; use ready once enough "
    "detail exists to draft an OpenAPI spec."
)

_SPEC_SYSTEM_PROMPT = (
    "You draft OpenAPI 3.1.0 specifications (schema apigen.openapi.v1). Respond with a single "
    "JSON envelope of the form {\"action\": \"final\", \"output\": {\"openapi\": \"3.1.0\", \"info\": {...}, "
    "\"paths\": {...}, \"components\": {...}}} and nothing else. Model only the resources and "
    "operations implied by the requirements; do not invent extra resources."
)

_APIGEN_CHILD_WORKFLOWS = {
    "apigen.generate": "ApiGenGenerateWorkflow.run",
    "apigen.validate": "ApiGenValidateWorkflow.run",
    "apigen.deploy": "ApiGenDeployWorkflow.run",
}


def _subworkflow_result(node_id: str, workflow_name: str, result: Any) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("status") != "succeeded":
        raise ValueError(
            f"subworkflow node {node_id!r} ({workflow_name!r}) did not succeed"
        )
    return {"value": result.get("output")}


async def _start_dag_child(
    run_id: str,
    trace_id: str,
    definition: dict[str, Any],
    user_input: str,
    runtime_config: dict[str, Any] | None,
) -> Any:
    return await workflow.execute_child_workflow(
        "XFlowsWorkflow.run",
        args=[definition, user_input, run_id, trace_id, runtime_config],
        id=run_id,
    )


async def _run_subworkflow_node(
    node: dict[str, Any],
    input_payload: dict[str, Any],
    run_id: str,
    trace_id: str,
    runtime_config: dict[str, Any] | None,
) -> dict[str, Any]:
    node_id = str(node.get("id", ""))
    params = node.get("params", {}) or {}
    workflow_name = str(params.get("workflowId") or params.get("workflow") or "")
    child_runtime = dict(runtime_config or {})
    override = params.get("runtimeConfig")
    if isinstance(override, dict):
        child_runtime.update(override)
    child_input = input_payload.get("value", "")

    if isinstance(params.get("workflowDefinition"), dict):
        result = await _start_dag_child(
            f"{run_id}:{node_id}",
            trace_id,
            params["workflowDefinition"],
            child_input if isinstance(child_input, str) else json.dumps(child_input, default=str),
            child_runtime,
        )
        return _subworkflow_result(node_id, "inline-definition", result)

    if workflow_name in _APIGEN_CHILD_WORKFLOWS:
        payload = child_input if isinstance(child_input, dict) else {"value": child_input}
        result = await workflow.execute_child_workflow(
            _APIGEN_CHILD_WORKFLOWS[workflow_name],
            args=[payload, run_id, trace_id, child_runtime],
            id=f"{run_id}:{node_id}",
        )
        return _subworkflow_result(node_id, workflow_name, result)

    if not workflow_name:
        raise ValueError(f"subworkflow node {node_id!r} is missing a workflow id")

    stored = await workflow.execute_activity(
        "xflows.load_workflow",
        args=[workflow_name],
        schedule_to_close_timeout=timedelta(seconds=30),
        retry_policy=node_retry_policy({}),
    )
    # The load_workflow activity may return either the raw definition or a
    # wrapper payload that embeds it under "definition".
    definition: Any = None
    if isinstance(stored, dict):
        candidate = stored.get("definition")
        if isinstance(candidate, dict):
            definition = candidate
        elif "nodes" in stored:
            definition = stored
    if not isinstance(definition, dict):
        raise ValueError(f"workflow {workflow_name!r} has no stored definition")
    result = await _start_dag_child(
        f"{run_id}:{node_id}",
        trace_id,
        definition,
        child_input if isinstance(child_input, str) else json.dumps(child_input, default=str),
        child_runtime,
    )
    return _subworkflow_result(node_id, workflow_name, result)


class ApprovalSignalsMixin:
    def __init__(self) -> None:
        self._approvals = ApprovalGate()

    @workflow.signal
    async def approve(self, payload: dict[str, Any] | None = None) -> None:
        self._record_approval_signal("approve", payload)

    @workflow.signal
    async def reject(self, payload: dict[str, Any] | None = None) -> None:
        self._record_approval_signal("reject", payload)

    @workflow.signal
    async def request_changes(self, payload: dict[str, Any] | None = None) -> None:
        self._record_approval_signal("request_changes", payload)

    def _record_approval_signal(self, signal_name: str, payload: dict[str, Any] | None) -> None:
        body = payload if isinstance(payload, dict) else {}
        node_id = str(body.get("nodeId", ""))
        # Decisions must be addressed to a node id; the API always sends one.
        if node_id:
            self._approvals.record(node_id, signal_name, body)

    async def _run_approval_node(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        run_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """Park on signals until approve/reject/request_changes or the timer fires."""
        node_id = str(node.get("id", ""))
        request = await workflow.execute_activity(
            "xflows.prepare_approval",
            args=[node, input_payload, run_id, trace_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=node_retry_policy({}),
        )
        try:
            timeout_s = float(request.get("signalTimeoutS", DEFAULT_SIGNAL_TIMEOUT_S))
        except (TypeError, ValueError):
            timeout_s = float(DEFAULT_SIGNAL_TIMEOUT_S)
        timeout_s = max(1.0, timeout_s)

        async def wait_for_decision() -> dict[str, Any]:
            await workflow.wait_condition(lambda: self._approvals.has(node_id))
            decision = self._approvals.get(node_id)
            assert decision is not None
            return decision

        try:
            decision = await asyncio.wait_for(wait_for_decision(), timeout=timeout_s)
        except asyncio.TimeoutError:
            decision = {"decision": "timeout", "reviewer": "", "comment": "", "evidence": {}}

        await workflow.execute_activity(
            "xflows.record_approval",
            args=[run_id, trace_id, node_id, decision],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=node_retry_policy({}),
        )
        return {
            "value": {
                "decision": decision.get("decision", "timeout"),
                "reviewer": decision.get("reviewer", ""),
                "comment": decision.get("comment", ""),
                "evidence": decision.get("evidence", {}),
            },
            "approval": {
                "decision": decision.get("decision", "timeout"),
                "reviewer": decision.get("reviewer", ""),
                "nodeId": node_id,
                "signalTimeoutS": timeout_s,
            },
        }


@workflow.defn(name="XFlowsWorkflow.run")
class XFlowsWorkflow(ApprovalSignalsMixin):
    @workflow.run
    async def run(
        self,
        workflow_def_payload: dict[str, Any],
        user_input: str,
        run_id: str,
        trace_id: str,
        runtime_config: dict[str, Any] | None = None,
        entry_node_id: str | None = None,
    ) -> dict[str, Any]:
        runtime_config = runtime_config or {}
        statuses: dict[str, str] = {}
        try:
            workflow_def = WorkflowDefinition.model_validate(workflow_def_payload)
            raw_nodes = [node.model_dump(mode="json") for node in workflow_def.nodes]
            raw_edges = [edge.model_dump(mode="json") for edge in workflow_def.edges]
            nodes, edges = normalize_workflow_graph(raw_nodes, raw_edges)
            runner = NodeGraphRunner(
                nodes=nodes, edges=edges, user_input=user_input, entry_node_id=entry_node_id
            )

            async def execute_node(node: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
                component_id = str(node.get("componentId") or "")
                if component_id == "Wait":
                    params = node.get("params", {}) or {}
                    try:
                        seconds = float(params.get("seconds", 1))
                    except (TypeError, ValueError):
                        seconds = 1.0
                    seconds = max(0.0, min(seconds, 3600.0))
                    # temporalio (1.8.0) has no workflow.sleep; asyncio.sleep is
                    # intercepted inside workflow context and becomes a durable timer.
                    await asyncio.sleep(seconds)
                    return {"value": input_payload.get("value", ""), "waitedSeconds": seconds}
                if component_id == "Approval":
                    return await self._run_approval_node(node, input_payload, run_id, trace_id)
                if component_id == "SubWorkflow":
                    return await _run_subworkflow_node(node, input_payload, run_id, trace_id, runtime_config or {})
                return await workflow.execute_activity(
                    "xflows.execute_node",
                    args=[node, input_payload, run_id, trace_id, runtime_config or {}],
                    schedule_to_close_timeout=node_timeout(node),
                    retry_policy=node_retry_policy(node),
                )

            outputs, order, statuses = await asyncio.wait_for(
                runner.run(execute_node),
                timeout=run_timeout(runtime_config).total_seconds(),
            )
            output_node_id = runner.resolve_output_node_id(order)
            output_value = outputs.get(output_node_id, {}).get("value", "")
            usage_totals = aggregate_usage(outputs)
            await workflow.execute_activity(
                "xflows.complete_run",
                args=[run_id, trace_id, "succeeded", {"output": output_value, "usage": usage_totals}],
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            return {"status": "succeeded", "output": output_value, "usage": usage_totals}
        except asyncio.TimeoutError as error:
            message = f"Workflow execution timed out after {run_timeout(runtime_config).total_seconds():.0f}s"
            await workflow.execute_activity(
                "xflows.complete_run",
                args=[run_id, trace_id, "failed", {"error": message}],
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            raise TimeoutError(message) from error
        except Exception as error:
            await workflow.execute_activity(
                "xflows.complete_run",
                args=[run_id, trace_id, "failed", {"error": str(error)}],
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            raise
        finally:
            pending_statuses = {
                node_id: status
                for node_id, status in statuses.items()
                if status not in ("succeeded",)
            }
            if pending_statuses:
                try:
                    await workflow.execute_activity(
                        "xflows.record_node_statuses",
                        args=[run_id, trace_id, pending_statuses],
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=node_retry_policy({}),
                    )
                except Exception:
                    workflow.logger.warning("Failed to record pending node statuses for run %s", run_id)


@workflow.defn(name="ApiGenGenerateWorkflow.run")
class ApiGenGenerateWorkflow(ApprovalSignalsMixin):
    @workflow.run
    async def run(
        self,
        user_input: Any,
        run_id: str,
        trace_id: str,
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_config = dict(runtime_config or {})
        stages: list[dict[str, Any]] = []

        def notify_stage(stage: dict[str, Any], status: str, **extra: Any) -> None:
            stages.append(_stage_record(stage, status, **extra))

        try:
            request_text = _extract_request_text(user_input)

            classify_stage = _stage(
                "classify",
                "AgentLoop",
                systemPrompt=_CLASSIFY_SYSTEM_PROMPT,
                outputSchema=CLASSIFICATION_SCHEMA,
            )
            classify_result = await _run_stage(
                run_id, trace_id, classify_stage, request_text, runtime_config
            )
            notify_stage(classify_stage, "succeeded")

            classify_validate_stage = _stage(
                "classify-validate",
                "SchemaValidate",
                schema=CLASSIFICATION_SCHEMA,
            )
            classify_validated = await _run_stage(
                run_id,
                trace_id,
                classify_validate_stage,
                classify_result.get("value"),
                runtime_config,
            )
            notify_stage(classify_validate_stage, "succeeded")
            decision_payload = _as_dict(classify_validated.get("value"))
            if str(decision_payload.get("decision", "")) != "accept":
                notify_stage(
                    classify_stage,
                    "rejected",
                    reason=decision_payload.get("reason", ""),
                    missing=decision_payload.get("missing", []),
                )
                return await _finish(
                    run_id,
                    trace_id,
                    "rejected",
                    {
                        "reason": decision_payload.get("reason", ""),
                        "missing": decision_payload.get("missing", []),
                    },
                    stages,
                )

            requirements: dict[str, Any] = {}
            feedback = ""
            context_text = request_text
            for clarify_round in range(1, MAX_CLARIFY_ROUNDS + 1):
                clarify_stage = _stage(
                    f"clarify-{clarify_round}",
                    "AgentLoop",
                    systemPrompt=_CLARIFY_SYSTEM_PROMPT,
                    outputSchema=CLARIFY_SCHEMA,
                )
                context_lines = [request_text]
                if requirements:
                    context_lines.append(json.dumps(requirements, default=str))
                if feedback:
                    context_lines.append(feedback)
                context_text = "\n".join(line for line in context_lines if line)
                try:
                    clarify_result = await _run_stage(
                        run_id, trace_id, clarify_stage, context_text, runtime_config
                    )
                except ActivityError:
                    notify_stage(clarify_stage, "invalid", error="schema validation failed")
                    feedback = "Previous response did not match the requirements schema; respond again."
                    continue
                clarify_validate_stage = _stage(
                    f"clarify-validate-{clarify_round}",
                    "SchemaValidate",
                    schema=CLARIFY_SCHEMA,
                )
                try:
                    validate_result = await _run_stage(
                        run_id,
                        trace_id,
                        clarify_validate_stage,
                        clarify_result.get("value"),
                        runtime_config,
                    )
                except ActivityError:
                    notify_stage(clarify_validate_stage, "invalid", error="schema validation failed")
                    feedback = "Previous response did not match the requirements schema; respond again."
                    continue
                notify_stage(clarify_stage, "succeeded")
                notify_stage(clarify_validate_stage, "succeeded")
                requirements = _as_dict(validate_result.get("value"))
                if str(requirements.get("action", "")) == "ready":
                    break
                questions = requirements.get("questions", [])
                feedback = "; ".join(str(q) for q in questions if q) or "More detail required."
            else:
                notify_stage(clarify_stage, "escalated", reason="clarify rounds exhausted")
                return await _finish(
                    run_id,
                    trace_id,
                    "needs_input",
                    {"reason": "clarify rounds exhausted", "questions": feedback},
                    stages,
                )

            spec: dict[str, Any] = {}
            spec_feedback = "Draft the OpenAPI specification from the requirements."
            for spec_round in range(1, MAX_CLARIFY_ROUNDS + 1):
                spec_stage = _stage(
                    f"spec-{spec_round}",
                    "AgentLoop",
                    systemPrompt=_SPEC_SYSTEM_PROMPT,
                    outputSchema=SPEC_SCHEMA,
                )
                spec_context_lines = [context_text, json.dumps(requirements, default=str)]
                if spec_feedback:
                    spec_context_lines.append(spec_feedback)
                try:
                    spec_result = await _run_stage(
                        run_id,
                        trace_id,
                        spec_stage,
                        "\n".join(line for line in spec_context_lines if line),
                        runtime_config,
                    )
                except ActivityError:
                    notify_stage(spec_stage, "invalid", error="schema validation failed")
                    spec_feedback = "Spec did not match the OpenAPI schema; try again."
                    continue
                spec_validate_stage = _stage(
                    f"spec-validate-{spec_round}",
                    "SchemaValidate",
                    schema=SPEC_SCHEMA,
                )
                try:
                    spec_validated = await _run_stage(
                        run_id,
                        trace_id,
                        spec_validate_stage,
                        spec_result.get("value"),
                        runtime_config,
                    )
                except ActivityError:
                    notify_stage(spec_validate_stage, "invalid", error="schema validation failed")
                    spec_feedback = "Spec did not match the OpenAPI schema; try again."
                    continue
                spec = _as_dict(spec_validated.get("value"))
                lint_errors = _lint_spec(spec)
                if lint_errors:
                    notify_stage(spec_validate_stage, "invalid", errors=lint_errors)
                    spec_feedback = "Spec lint errors: " + "; ".join(lint_errors)
                    continue
                notify_stage(spec_stage, "succeeded")
                notify_stage(spec_validate_stage, "succeeded")
                break
            else:
                return await _finish(
                    run_id,
                    trace_id,
                    "failed",
                    {"error": "spec generation failed"},
                    stages,
                )

            codegen_stage = _stage("codegen", "Codegen")
            codegen_result = await _run_stage(
                run_id,
                trace_id,
                codegen_stage,
                spec,
                runtime_config,
                timeout_s=300.0,
            )
            notify_stage(codegen_stage, "succeeded")
            bundle = _as_dict(codegen_result.get("value"))
            bundle_hash = str(bundle.get("hash", ""))

            validate_child_result: dict[str, Any] = {}
            for repair_round in range(1, MAX_REPAIR_ROUNDS + 1):
                try:
                    validate_child_result = await workflow.execute_child_workflow(
                        "ApiGenValidateWorkflow.run",
                        args=[{"spec": spec, "bundle": bundle}, run_id, trace_id, runtime_config],
                        id=f"{run_id}:validate-{repair_round}",
                    )
                except Exception:
                    validate_child_result = {
                        "status": "failed",
                        "output": {"error": "bundle validation child workflow failed"},
                    }
                if isinstance(validate_child_result, dict) and validate_child_result.get("status") == "succeeded":
                    break
                repair_stage = _stage(f"repair-{repair_round}", "Codegen")
                codegen_result = await _run_stage(
                    run_id,
                    trace_id,
                    repair_stage,
                    spec,
                    runtime_config,
                    timeout_s=300.0,
                )
                notify_stage(repair_stage, "succeeded")
                bundle = _as_dict(codegen_result.get("value"))
                bundle_hash = str(bundle.get("hash", ""))
            else:
                return await _finish(
                    run_id,
                    trace_id,
                    "failed",
                    {
                        "error": "bundle validation failed after repair rounds",
                        "validation": validate_child_result.get("output"),
                    },
                    stages,
                )

            review_stage = _stage("review", "Approval")
            review = await self._run_approval_node(
                review_stage,
                {
                    "value": {
                        "summary": f"API spec {bundle_hash} ready for review",
                        "spec": spec,
                        "bundleHash": bundle_hash,
                    }
                },
                run_id,
                trace_id,
            )
            notify_stage(review_stage, "succeeded")
            review_value = _as_dict(review.get("value"))
            if str(review_value.get("decision", "")) not in ("approve", "approved"):
                return await _finish(
                    run_id,
                    trace_id,
                    "rejected",
                    {"review": review_value},
                    stages,
                )

            policy_stage = _stage(
                "policy",
                "XWSIAMEvaluate",
                action="apigen:deploy",
                resource=f"bundle:{bundle_hash}",
                principal=str(runtime_config.get("principal") or "apigen-pipeline"),
            )
            policy_result = await _run_stage(
                run_id,
                trace_id,
                policy_stage,
                {"decision": "approve"},
                runtime_config,
                timeout_s=60.0,
                attempts=1,
            )
            notify_stage(policy_stage, "succeeded")
            policy_value = _as_dict(policy_result.get("value"))
            allowed = policy_value.get("allowed", policy_value.get("decision", True))
            if allowed in (False, "false", "False", "deny", "denied"):
                return await _finish(
                    run_id,
                    trace_id,
                    "rejected",
                    {"policy": policy_value},
                    stages,
                )

            secret_bindings = {
                key[:-3]: runtime_config[key]
                for key in runtime_config
                if key.endswith("Ref") and isinstance(runtime_config[key], str)
            }
            try:
                deploy_child = await workflow.execute_child_workflow(
                    "ApiGenDeployWorkflow.run",
                    args=[
                        {
                            "spec": spec,
                            "bundle": bundle,
                            "bundleHash": bundle_hash,
                            "secretBindings": secret_bindings,
                        },
                        run_id,
                        trace_id,
                        runtime_config,
                    ],
                    id=f"{run_id}:deploy",
                )
            except Exception as error:
                return await _finish(
                    run_id,
                    trace_id,
                    "failed",
                    {"error": f"deploy failed: {error}"},
                    stages,
                )
            if not isinstance(deploy_child, dict) or deploy_child.get("status") != "succeeded":
                return await _finish(
                    run_id,
                    trace_id,
                    "failed",
                    {"error": "deploy child workflow did not succeed"},
                    stages,
                )
            manifest = _as_dict(_as_dict(deploy_child.get("output")).get("manifest"))
            return await _finish(
                run_id,
                trace_id,
                "succeeded",
                {
                    "bundleHash": bundle_hash,
                    "spec": spec,
                    "manifest": manifest,
                    "registrationDeferred": True,
                },
                stages,
            )
        except Exception as error:
            return await _finish(
                run_id,
                trace_id,
                "failed",
                {"error": str(error)},
                stages,
            )


@workflow.defn(name="ApiGenValidateWorkflow.run")
class ApiGenValidateWorkflow:
    @workflow.run
    async def run(
        self,
        input_payload: Any,
        run_id: str,
        trace_id: str,
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = input_payload if isinstance(input_payload, dict) else {}
        bundle = _as_dict(value.get("bundle"))
        bundle_hash = str(value.get("bundleHash") or bundle.get("hash") or "")
        if not bundle_hash:
            return {
                "status": "failed",
                "output": {"error": "bundle hash is required for validation"},
            }
        validate_stage = _stage(
            "validate",
            "XWSLambdaInvoke",
            functionName="apigen-bundle-validator",
            bundleHash=bundle_hash,
        )
        result = await _run_stage(
            run_id,
            trace_id,
            validate_stage,
            _as_dict(value.get("payload")) or {"bundleHash": bundle_hash},
            runtime_config,
            timeout_s=600.0,
            attempts=1,
        )
        return {
            "status": "succeeded",
            "output": _as_dict(result.get("value")) or {"result": result.get("value")},
        }


@workflow.defn(name="ApiGenDeployWorkflow.run")
class ApiGenDeployWorkflow:
    @workflow.run
    async def run(
        self,
        input_payload: Any,
        run_id: str,
        trace_id: str,
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_config = dict(runtime_config or {})
        value = input_payload if isinstance(input_payload, dict) else {}
        bundle_hash = str(value.get("bundleHash") or _as_dict(value.get("bundle")).get("hash") or "")
        if not bundle_hash:
            return {
                "status": "failed",
                "output": {"error": "bundle hash is required for deployment"},
            }
        secret_bindings = value.get("secretBindings")
        if not isinstance(secret_bindings, dict) or not secret_bindings:
            secret_bindings = {
                key[:-3]: runtime_config[key]
                for key in runtime_config
                if key.endswith("Ref") and isinstance(runtime_config[key], str)
            }
        deploy_stage = _stage(
            "deploy",
            "XWSLambdaInvoke",
            functionName="apigen-deployer",
            bundleHash=bundle_hash,
            **({"secretBindings": secret_bindings} if secret_bindings else {}),
        )
        result = await _run_stage(
            run_id,
            trace_id,
            deploy_stage,
            {"bundleHash": bundle_hash, "secretBindings": secret_bindings},
            runtime_config,
            timeout_s=300.0,
            attempts=1,
        )
        deploy_output = _as_dict(result.get("value"))
        aliases = deploy_output.get("aliases") if isinstance(deploy_output.get("aliases"), dict) else {
            "sandbox": f"sandbox:{bundle_hash}",
            "live": f"live:{bundle_hash}",
        }
        spec = _as_dict(value.get("spec"))
        spec_hash = hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        manifest = {
            "bundleHash": bundle_hash,
            "specHash": spec_hash,
            "aliases": aliases,
            "deployedAt": workflow.now().isoformat(),
        }
        return {
            "status": "succeeded",
            "output": {"manifest": manifest, "deploy": deploy_output},
        }
