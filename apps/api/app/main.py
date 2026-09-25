from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from secrets import token_hex
from typing import Any, AsyncGenerator
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sse_starlette.sse import EventSourceResponse

from xflows_engine import NodeGraphRunner, create_default_registry, normalize_workflow_graph
from xflows_engine.context import SECRET_KEY_PATTERN, NodeExecutionContext, scoped_runtime_config

from .auth import Caller, caller_dependency, require_project_access, require_role
from .config import settings
from .models import (
    ApprovalDecisionRequest,
    InternalRunEventRequest,
    ProjectCreateRequest,
    ProjectRecord,
    ProjectRunRequest,
    ProjectSecretPutRequest,
    ProjectSecretRecord,
    ProjectUpdateRequest,
    RunEvent,
    RunRecord,
    RunRequest,
    TriggerCreateRequest,
    TriggerRecord,
    TriggerUpdateRequest,
    UserCreateRequest,
    UserRecord,
    WorkflowCreateRequest,
    WorkflowRecord,
)
from .persistence import create_store
from .store import BaseStore, InMemoryStore, utc_now
from .temporal_client import TemporalGateway
from .triggers import trigger_scheduler_loop, webhook_signature
from .xws_sigv4 import parse_auth_header, verify_request

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger = logging.getLogger(__name__)
store: BaseStore = InMemoryStore()
temporal_gateway = TemporalGateway()
RUNS_CREATED = Counter("xflows_runs_created_total", "Total runs created")
RUNS_COMPLETED = Counter("xflows_runs_completed_total", "Total runs completed", ["status"])
RUN_CREATE_LATENCY = Histogram("xflows_run_create_latency_seconds", "Latency for run create API")
FALLBACK_ACTIVATIONS = Counter(
    "xflows_local_fallback_activations_total", "Legacy local-run fallback activations"
)
node_registry = create_default_registry()


@app.on_event("startup")
async def startup() -> None:
    global store
    store = await create_store(settings)
    logger.info("Persistence store initialized: %s", settings.persistence_mode)

    async def create_run_for_trigger(workflow_id: str, idempotency_key: str, input_value: str):
        try:
            return await _create_run_impl(workflow_id, RunRequest(input=input_value, idempotencyKey=idempotency_key))
        except HTTPException:
            return None

    if settings.trigger_scheduler_interval_s > 0:
        app.state.trigger_task = asyncio.create_task(
            trigger_scheduler_loop(
                store,
                create_run_for_trigger,
                interval_s=settings.trigger_scheduler_interval_s,
            )
        )
        logger.info(
            "Trigger scheduler started (interval=%ss)", settings.trigger_scheduler_interval_s
        )


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "trigger_task", None)
    if task is not None:
        task.cancel()
    await store.close()


async def emit_event(
    run_id: str,
    event_type: str,
    node_id: str | None = None,
    payload: dict | None = None,
    trace_id: str | None = None,
    event_key: str | None = None,
) -> RunEvent:
    event = RunEvent(
        runId=run_id,
        type=event_type,
        nodeId=node_id,
        payload=payload or {},
        timestamp=utc_now(),
        traceId=trace_id,
        eventKey=event_key,
    )
    return await store.append_event(event)


def require_internal_token(x_internal_token: str | None) -> None:
    configured = settings.internal_token_set
    if configured and x_internal_token not in configured:
        raise HTTPException(status_code=401, detail="Invalid internal token")


PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
}


def _estimate_cost(model: str, usage: dict[str, Any]) -> float | None:
    key = str(model).removeprefix("xws/").split("/", 1)[-1].lower()
    prices = PRICE_PER_1M_TOKENS.get(key)
    if prices is None:
        return None
    try:
        input_value = float(usage.get("input") or 0)
        output_value = float(usage.get("output") or 0)
    except (TypeError, ValueError):
        return None
    return round(input_value / 1_000_000 * prices[0] + output_value / 1_000_000 * prices[1], 6)


def _normalize_usage(raw_usage: dict[str, Any], model: str) -> dict[str, Any]:
    prompt_tokens = raw_usage.get("prompt_tokens", raw_usage.get("input_tokens"))
    completion_tokens = raw_usage.get("completion_tokens", raw_usage.get("output_tokens"))
    total_tokens = raw_usage.get("total_tokens")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        try:
            total_tokens = int(prompt_tokens) + int(completion_tokens)
        except (TypeError, ValueError):
            total_tokens = None
    normalized: dict[str, Any] = {
        "input": prompt_tokens,
        "output": completion_tokens,
        "total": total_tokens,
    }
    cost = _estimate_cost(model, normalized)
    if cost is not None:
        normalized["costUsd"] = cost
    return normalized


def _aggregate_usage(outputs: dict[str, Any]) -> dict[str, Any]:
    totals = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "costEstimateUsd": 0.0, "nodes": 0}
    for result in outputs.values():
        usage = result.get("usage") if isinstance(result, dict) and isinstance(result.get("usage"), dict) else None
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


async def run_litellm_chat(
    prompt: str,
    system_prompt: str | None = None,
    model_hint: str | None = None,
    temperature: float = 0.2,
    runtime_config: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    runtime_config = runtime_config or {}
    model = model_hint or str(runtime_config.get("litellmModel") or settings.litellm_model_alias)
    headers = {"Content-Type": "application/json"}
    auth_key = (
        api_key
        or runtime_config.get("litellmApiKey")
        or settings.litellm_api_key
        or settings.litellm_master_key
    )
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    base_url = str(base_url or runtime_config.get("litellmBaseUrl") or settings.litellm_base_url).strip().rstrip("/")
    base_url = base_url.removesuffix("/v1")
    candidate_models = [model]

    last_error = "LiteLLM request failed"
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        for candidate_model in dict.fromkeys(candidate_models):
            payload = {
                "model": candidate_model,
                "messages": (
                    [{"role": "system", "content": system_prompt}] if system_prompt else []
                )
                + [{"role": "user", "content": prompt}],
                "temperature": temperature,
            }
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if stop:
                payload["stop"] = list(stop)
            if response_format is not None:
                payload["response_format"] = response_format
            if tools:
                payload["tools"] = tools
            response = await client.post("/v1/chat/completions", headers=headers, json=payload)
            if response.status_code < 400:
                data = response.json()
                return {
                    "content": data["choices"][0]["message"]["content"],
                    "provider": "litellm",
                    "model": candidate_model,
                    "usage": _normalize_usage(data.get("usage", {}), candidate_model),
                }
            body = response.text.strip()
            last_error = (
                f"LiteLLM chat failed (status={response.status_code}, model={candidate_model}, "
                f"url={base_url}/v1/chat/completions): "
                f"{body or response.reason_phrase}"
            )
            break
    raise RuntimeError(last_error)


async def _resolve_runtime_config(
    project_id: str | None, inline: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a run's effective runtimeConfig and its redacted, persistable copy.

    Project configs are the base (so trigger-fired runs and runs started from
    another browser still get the project's LiteLLM URL/model), overlaid by the
    caller's inline runtimeConfig. Secret-shaped project configs are stored in
    ``project_secrets`` (fix XF-01) — for each one the caller did not supply
    inline, a ``<key>Ref`` is added so the worker resolves it at execution time.
    """
    config: dict[str, Any] = {}
    if project_id:
        project = await store.get_project(project_id)
        if project and isinstance(project.configs, dict):
            config.update(project.configs)
        for row in await store.list_project_secret_names(project_id):
            name = str(row.get("name", ""))
            if SECRET_KEY_PATTERN.search(name) and f"{name}Ref" not in (inline or {}):
                config[f"{name}Ref"] = name
    config.update(inline or {})
    for key in [k for k in config if k.endswith("Ref") and k[:-3] in config]:
        config.pop(key)
    redacted = {
        key: ("***" if SECRET_KEY_PATTERN.search(key) and not key.endswith("Ref") and value else value)
        for key, value in config.items()
    }
    return config, redacted


async def _resolve_local_secret_refs(config: dict[str, Any], project_id: str | None) -> dict[str, Any]:
    """Local-fallback twin of the worker's ``_resolve_secret_refs``."""
    resolved = dict(config)
    for ref_key in [k for k, v in config.items() if k.endswith("Ref") and isinstance(v, str)]:
        value = await store.get_project_secret(project_id, config[ref_key]) if project_id else None
        if value is not None:
            resolved[ref_key[:-3]] = value
            resolved.pop(ref_key)
    return resolved


async def execute_local_run(
    run: RunRecord, workflow: WorkflowRecord, runtime_config: dict[str, Any] | None = None
) -> None:
    run.status = "running"
    run.startedAt = run.startedAt or utc_now()
    await store.update_run(run)
    run_timeout_seconds = 900.0

    try:
        raw_nodes = [node.model_dump(mode="json") for node in workflow.nodes]
        raw_edges = [edge.model_dump(mode="json") for edge in workflow.edges]
        nodes, edges = normalize_workflow_graph(raw_nodes, raw_edges)
        entry_node_id = run.metadata.get("entryNodeId") if isinstance(run.metadata, dict) else None
        runner = NodeGraphRunner(
            nodes=nodes, edges=edges, user_input=run.input, entry_node_id=entry_node_id
        )
        if runtime_config is None:
            runtime_config = (
                run.metadata.get("runtimeConfig", {})
                if isinstance(run.metadata.get("runtimeConfig"), dict)
                else {}
            )
        runtime_config = await _resolve_local_secret_refs(runtime_config, run.projectId)

        async def llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float, **options: Any) -> dict[str, Any]:
            return await run_litellm_chat(
                prompt,
                system_prompt,
                model_hint,
                temperature,
                runtime_config=runtime_config,
                **options,
            )

        async def make_context(node: dict[str, Any]) -> NodeExecutionContext:
            # fix XF-06: nodes receive only their class's config — secret-shaped
            # keys are stripped unless the component genuinely needs them.
            component_id = str(node.get("componentId") or "")
            node_config = scoped_runtime_config(component_id, runtime_config)
            return NodeExecutionContext(
                run_id=run.id,
                trace_id=run.traceId,
                user_input=run.input,
                llm_chat=llm_chat,
                http_request=_http_request,
                runtime_config=node_config,
            )

        async def execute(node: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
            node_id = node.get("id", "unknown")
            component_id = str(node.get("componentId") or "")
            context = await make_context(node)
            if component_id == "Wait":
                params = node.get("params", {}) or {}
                try:
                    seconds = float(params.get("seconds", 1))
                except (TypeError, ValueError):
                    seconds = 1.0
                seconds = max(0.0, min(seconds, 3600.0))
                await asyncio.sleep(seconds)
                return {"value": input_payload.get("value", ""), "waitedSeconds": seconds}
            await emit_event(run.id, "node_started", node_id=node_id, trace_id=run.traceId)
            retry = node.get("retry") if isinstance(node.get("retry"), dict) else {}
            try:
                attempts = max(1, int(retry.get("attempts", 3)))
                backoff_ms = max(0.0, float(retry.get("backoffMs", 1000)))
            except (TypeError, ValueError):
                attempts, backoff_ms = 3, 1000.0
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    result = await node_registry.dispatch(node=node, input_payload=input_payload, context=context)
                    await emit_event(
                        run.id,
                        "node_succeeded",
                        node_id=node_id,
                        payload={
                            "output": result.get("value"),
                            "metadata": {k: v for k, v in result.items() if k != "value"},
                            "attempt": attempt,
                        },
                        trace_id=run.traceId,
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    if attempt < attempts and backoff_ms > 0:
                        await asyncio.sleep(backoff_ms / 1000.0)
            raise last_error if last_error else RuntimeError(f"Node {node_id} failed")

        try:
            configured_timeout = float(runtime_config.get("executionTimeoutS", 900))
            run_timeout_seconds = max(1.0, min(configured_timeout, 86400.0))
        except (TypeError, ValueError):
            pass

        outputs, order, statuses = await asyncio.wait_for(
            runner.run(execute),
            timeout=run_timeout_seconds,
        )

        final_node_id = runner.resolve_output_node_id(order)
        run.status = "succeeded"
        run.output = str(outputs.get(final_node_id, {}).get("value", ""))
        run.finishedAt = utc_now()
        usage_totals = _aggregate_usage(outputs)
        if usage_totals.get("nodes"):
            run.metadata = {**(run.metadata or {}), "usage": usage_totals}
        await store.update_run(run)
        RUNS_COMPLETED.labels(status="succeeded").inc()
        for node_id, status in statuses.items():
            if status == "skipped":
                await emit_event(run.id, "node_skipped", node_id=node_id, payload={"status": status}, trace_id=run.traceId)
            elif status == "failed_routed":
                await emit_event(run.id, "node_routed_to_error", node_id=node_id, payload={"status": status}, trace_id=run.traceId)
        await emit_event(
            run.id,
            "run_succeeded",
            payload={"output": run.output},
            trace_id=run.traceId,
        )
    except asyncio.TimeoutError:
        run.status = "failed"
        run.error = f"Workflow execution timed out after {run_timeout_seconds:.0f}s"
        run.finishedAt = utc_now()
        await store.update_run(run)
        RUNS_COMPLETED.labels(status="failed").inc()
        await emit_event(
            run.id,
            "run_failed",
            payload={"error": run.error},
            trace_id=run.traceId,
        )
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finishedAt = utc_now()
        await store.update_run(run)
        RUNS_COMPLETED.labels(status="failed").inc()
        await emit_event(
            run.id,
            "run_failed",
            payload={"error": run.error or "Workflow failed"},
            trace_id=run.traceId,
        )


async def _http_request(method: str, url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url)
        response.raise_for_status()
        return response.text


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    status = await temporal_gateway.connect()
    return {
        "status": "ok",
        "temporal": "connected" if status.connected else f"disconnected: {status.reason}",
    }


@app.post("/users", response_model=UserRecord)
async def create_user(payload: UserCreateRequest, caller: Caller = Depends(caller_dependency)) -> UserRecord:
    require_role(caller, "owner")
    return await store.create_user(payload)


@app.get("/users", response_model=list[UserRecord])
async def list_users(caller: Caller = Depends(caller_dependency)) -> list[UserRecord]:
    return await store.list_users()


@app.get("/users/{user_id}", response_model=UserRecord)
async def get_user(user_id: str, caller: Caller = Depends(caller_dependency)) -> UserRecord:
    user = await store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


@app.post("/projects", response_model=ProjectRecord)
async def create_project(payload: ProjectCreateRequest, caller: Caller = Depends(caller_dependency)) -> ProjectRecord:
    require_role(caller, "owner")
    return await store.create_project(payload)


@app.get("/projects", response_model=list[ProjectRecord])
async def list_projects(caller: Caller = Depends(caller_dependency)) -> list[ProjectRecord]:
    return await store.list_projects()


@app.get("/projects/{project_id}", response_model=ProjectRecord)
async def get_project(project_id: str, caller: Caller = Depends(caller_dependency)) -> ProjectRecord:
    require_project_access(caller, project_id)
    project = await store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@app.patch("/projects/{project_id}", response_model=ProjectRecord)
async def update_project(
    project_id: str, payload: ProjectUpdateRequest, caller: Caller = Depends(caller_dependency)
) -> ProjectRecord:
    require_role(caller, "owner")
    require_project_access(caller, project_id)
    project = await store.update_project(project_id, payload)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, caller: Caller = Depends(caller_dependency)) -> dict[str, bool]:
    require_role(caller, "owner")
    require_project_access(caller, project_id)
    deleted = await store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return {"deleted": True}


@app.put("/projects/{project_id}/secrets", response_model=list[ProjectSecretRecord])
async def put_project_secret(
    project_id: str, payload: ProjectSecretPutRequest, caller: Caller = Depends(caller_dependency)
) -> list[ProjectSecretRecord]:
    require_role(caller, "owner")
    require_project_access(caller, project_id)
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    # fix XF-01: secret values live in the dedicated secrets store, never in
    # project configs JSONB; they are never returned through the API.
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Secret name required")
    await store.set_project_secret(project_id, name, payload.value)
    return await list_project_secrets(project_id, caller)


@app.get("/projects/{project_id}/secrets", response_model=list[ProjectSecretRecord])
async def list_project_secrets(project_id: str, caller: Caller = Depends(caller_dependency)) -> list[ProjectSecretRecord]:
    require_role(caller, "owner")
    require_project_access(caller, project_id)
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    rows = await store.list_project_secret_names(project_id)
    return [ProjectSecretRecord.model_validate(row) for row in rows]


@app.get("/projects/{project_id}/triggers", response_model=list[TriggerRecord])
async def list_project_triggers(
    project_id: str, caller: Caller = Depends(caller_dependency)
) -> list[TriggerRecord]:
    require_project_access(caller, project_id)
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return await store.list_triggers(project_id)


@app.post("/projects/{project_id}/triggers", response_model=TriggerRecord)
async def create_project_trigger(
    project_id: str, payload: TriggerCreateRequest, caller: Caller = Depends(caller_dependency)
) -> TriggerRecord:
    require_role(caller, "operator")
    require_project_access(caller, project_id)
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    config = payload.config
    _entry_node_components = {
        "webhook": ("Webhook", "WebhookTrigger"),
        "event": ("XWSEventTrigger",),
    }
    if payload.type in _entry_node_components and config.get("nodeId"):
        # Soft validation: a nodeId that's present must be real; a nodeId
        # that's absent is fine (degrades to broadcast-to-all-entry-nodes).
        target_workflow = await store.get_workflow(str(config.get("workflowId", "")))
        if target_workflow:
            matching = next(
                (n for n in target_workflow.nodes if n.id == config["nodeId"]), None
            )
            if not matching or matching.componentId not in _entry_node_components[payload.type]:
                raise HTTPException(
                    status_code=400,
                    detail=f"config.nodeId does not reference a {payload.type} trigger node on this workflow",
                )
    if payload.type == "webhook":
        # XU-8: registration secret generated at creation; used for HMAC
        # verification of deliveries on POST /webhooks/{trigger_id}.
        config = {**config, "signatureSecret": config.get("signatureSecret") or token_hex(16)}
    elif payload.type == "event":
        # SigV4 key pair for XWS-originated deliveries on POST /events/{trigger_id}.
        # Handed to the calling XWS service (e.g. a lambda-svc FunctionTrigger),
        # which signs with its own existing xws_common signing code.
        config = {
            **config,
            "accessKeyId": config.get("accessKeyId") or f"evt_{token_hex(8)}",
            "secretAccessKey": config.get("secretAccessKey") or token_hex(32),
        }
    return await store.create_trigger(project_id, TriggerCreateRequest(
        type=payload.type,
        enabled=payload.enabled,
        config=config,
    ))


@app.patch("/projects/{project_id}/triggers/{trigger_id}", response_model=TriggerRecord)
async def update_project_trigger(
    project_id: str,
    trigger_id: str,
    payload: TriggerUpdateRequest,
    caller: Caller = Depends(caller_dependency),
) -> TriggerRecord:
    require_role(caller, "operator")
    require_project_access(caller, project_id)
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    updated = await store.update_trigger(project_id, trigger_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")
    return updated


@app.delete("/projects/{project_id}/triggers/{trigger_id}")
async def delete_project_trigger(
    project_id: str, trigger_id: str, caller: Caller = Depends(caller_dependency)
) -> dict[str, bool]:
    require_role(caller, "operator")
    require_project_access(caller, project_id)
    deleted = await store.delete_trigger(project_id, trigger_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")
    return {"deleted": True}


@app.post("/workflows", response_model=WorkflowRecord)
async def create_workflow(payload: WorkflowCreateRequest, caller: Caller = Depends(caller_dependency)) -> WorkflowRecord:
    require_role(caller, "owner")
    require_project_access(caller, payload.metadata.get("projectId"))
    if await store.get_workflow(payload.id):
        raise HTTPException(status_code=409, detail=f"Workflow {payload.id} already exists")
    return await store.create_workflow(payload)


@app.get("/workflows", response_model=list[WorkflowRecord])
async def list_workflows(caller: Caller = Depends(caller_dependency)) -> list[WorkflowRecord]:
    return await store.list_workflows()


@app.post("/workflows/{workflow_id}/publish", response_model=WorkflowRecord)
async def publish_workflow(workflow_id: str, caller: Caller = Depends(caller_dependency)) -> WorkflowRecord:
    require_role(caller, "operator")
    updated = await store.set_workflow_status(workflow_id, "published")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return updated


@app.post("/workflows/{workflow_id}/archive", response_model=WorkflowRecord)
async def archive_workflow(workflow_id: str, caller: Caller = Depends(caller_dependency)) -> WorkflowRecord:
    require_role(caller, "operator")
    updated = await store.set_workflow_status(workflow_id, "archived")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return updated


@app.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, caller: Caller = Depends(caller_dependency)) -> dict[str, bool]:
    require_role(caller, "owner")
    if not await store.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    # fix XF-05: run history is retained — refuse deletion when runs exist.
    if await store.workflow_run_count(workflow_id):
        raise HTTPException(
            status_code=409,
            detail=f"Workflow {workflow_id} has runs; archive it instead of deleting",
        )
    deleted = await store.delete_workflow(workflow_id)
    return {"deleted": deleted}


@app.post("/workflows/{workflow_id}/runs", response_model=RunRecord)
async def create_run(
    workflow_id: str, payload: RunRequest, caller: Caller = Depends(caller_dependency)
) -> RunRecord:
    require_role(caller, "operator")
    workflow = await store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    require_project_access(caller, workflow.metadata.get("projectId"))
    with RUN_CREATE_LATENCY.time():
        return await _create_run_impl(workflow_id, payload)


@app.post("/projects/{project_id}/runs", response_model=RunRecord)
async def create_project_run(
    project_id: str, payload: ProjectRunRequest, caller: Caller = Depends(caller_dependency)
) -> RunRecord:
    require_role(caller, "operator")
    require_project_access(caller, project_id)
    await store.ensure_project(project_id)

    workflow_payload = WorkflowCreateRequest(
        id=f"wf_{project_id}",
        name=payload.workflow.name,
        description=payload.workflow.description,
        nodes=payload.workflow.nodes,
        edges=payload.workflow.edges,
        metadata={
            **payload.workflow.metadata,
            "projectId": project_id,
            "source": "project_run",
        },
    )
    workflow = await store.upsert_workflow(workflow_payload)
    run_request = RunRequest(
        input=payload.input,
        idempotencyKey=payload.idempotencyKey,
        metadata={**payload.metadata, "projectId": project_id},
    )
    with RUN_CREATE_LATENCY.time():
        return await _create_run_impl(workflow.id, run_request, project_id=project_id)


@app.get("/projects/{project_id}/runs", response_model=list[RunRecord])
async def list_project_runs(project_id: str, caller: Caller = Depends(caller_dependency)) -> list[RunRecord]:
    require_project_access(caller, project_id)
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return await store.list_runs(project_id)


_APIGEN_RUN_WORKFLOWS = {
    "apigen.generate": "ApiGenGenerateWorkflow.run",
    "apigen.validate": "ApiGenValidateWorkflow.run",
    "apigen.deploy": "ApiGenDeployWorkflow.run",
}


async def _create_run_impl(
    workflow_id: str, payload: RunRequest, project_id: str | None = None
) -> RunRecord:
    workflow = await store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    if workflow.status == "archived":
        raise HTTPException(status_code=409, detail=f"Workflow {workflow_id} is archived")

    if payload.idempotencyKey:
        # A duplicate delivery must return the original run without starting it
        # again: re-starting would hit Temporal's duplicate workflow id, which
        # used to fall through to the local fallback and execute a second time.
        existing = await store.find_run_by_idempotency_key(workflow_id, payload.idempotencyKey)
        if existing is not None:
            return existing

    project_id = project_id or (
        str(workflow.metadata.get("projectId") or "") if isinstance(workflow.metadata, dict) else ""
    ) or None
    metadata = dict(payload.metadata or {})
    inline_config = metadata.get("runtimeConfig") if isinstance(metadata.get("runtimeConfig"), dict) else {}
    runtime_config, redacted_config = await _resolve_runtime_config(project_id, inline_config)
    if redacted_config:
        metadata["runtimeConfig"] = redacted_config
    if payload.entryNodeId:
        metadata["entryNodeId"] = payload.entryNodeId

    trace_id = f"trace_{uuid4().hex[:16]}"
    run = await store.create_run(
        workflow_id,
        workflow.version,
        payload.input,
        trace_id=trace_id,
        project_id=project_id,
        metadata=metadata,
        idempotency_key=payload.idempotencyKey,
    )
    RUNS_CREATED.inc()
    await emit_event(run.id, "run_started", trace_id=trace_id)
    apigen_kind = str(workflow.metadata.get("apigen", "")) if isinstance(workflow.metadata, dict) else ""
    if apigen_kind in _APIGEN_RUN_WORKFLOWS:
        temporal_status = await temporal_gateway.start_workflow(
            workflow_name=_APIGEN_RUN_WORKFLOWS[apigen_kind],
            workflow_id=f"{workflow_id}:{run.id}",
            args=[run.input, run.id, trace_id, runtime_config],
        )
    else:
        temporal_status = await temporal_gateway.start_workflow(
            workflow_name="XFlowsWorkflow.run",
            workflow_id=f"{workflow_id}:{run.id}",
            args=[
                workflow.model_dump(mode="json"),
                run.input,
                run.id,
                trace_id,
                runtime_config,
                payload.entryNodeId,
            ],
        )

    if temporal_status.connected:
        run.status = "running"
        run.startedAt = utc_now()
        await store.update_run(run)
    elif workflow.durable:
        # fix XF-03: no fire-and-forget fallback for durable (pipeline) runs.
        run.status = "failed"
        run.error = "Temporal unavailable; durable workflows refuse local fallback"
        run.finishedAt = utc_now()
        await store.update_run(run)
        await emit_event(run.id, "run_failed", payload={"error": run.error}, trace_id=trace_id)
        RUNS_COMPLETED.labels(status="failed").inc()
        raise HTTPException(status_code=503, detail=run.error)
    else:
        # Legacy local fallback for non-durable workflows so the test panel
        # keeps working without Temporal; alert metric tracks usage.
        FALLBACK_ACTIVATIONS.inc()
        asyncio.create_task(execute_local_run(run, workflow, runtime_config))

    return run


@app.get("/runs/{run_id}", response_model=RunRecord)
async def get_run(run_id: str, caller: Caller = Depends(caller_dependency)) -> RunRecord:
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    require_project_access(caller, run.projectId)
    return run


@app.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    caller: Caller = Depends(caller_dependency),
    after_id: int | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    require_project_access(caller, run.projectId)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        cursor = after_id
        if last_event_id and last_event_id.isdigit():
            cursor = int(last_event_id)
        idle_ticks = 0

        while idle_ticks < 300:
            events = await store.get_events(run_id, after_id=cursor, limit=200)
            if events:
                for event in events:
                    yield {
                        "id": str(event.id or ""),
                        "event": event.type,
                        "data": event.model_dump_json(),
                    }
                cursor = events[-1].id or cursor
                idle_ticks = 0
            else:
                idle_ticks += 1
            await asyncio.sleep(0.2)

    return EventSourceResponse(event_stream())


@app.get("/runs/{run_id}/events/history", response_model=list[RunEvent])
async def list_run_events(
    run_id: str,
    caller: Caller = Depends(caller_dependency),
    after_id: int | None = Query(default=None),
) -> list[RunEvent]:
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    require_project_access(caller, run.projectId)
    return await store.get_events(run_id, after_id=after_id, limit=2000)


@app.post("/internal/runs/{run_id}/events", response_model=RunEvent)
async def append_internal_event(
    run_id: str,
    payload: InternalRunEventRequest,
    x_internal_token: str | None = Header(default=None),
) -> RunEvent:
    require_internal_token(x_internal_token)
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    event = await emit_event(
        run_id=run_id,
        event_type=payload.type,
        node_id=payload.nodeId,
        payload=payload.payload,
        trace_id=payload.traceId or run.traceId,
        event_key=payload.eventKey,
    )
    if payload.type == "run_succeeded":
        run.status = "succeeded"
        run.output = payload.payload.get("output")
        run.finishedAt = utc_now()
        usage = payload.payload.get("usage")
        if isinstance(usage, dict) and usage.get("nodes"):
            run.metadata = {**(run.metadata or {}), "usage": usage}
        await store.update_run(run)
        RUNS_COMPLETED.labels(status="succeeded").inc()
    elif payload.type == "run_failed":
        run.status = "failed"
        run.error = payload.payload.get("error", "Workflow failed")
        run.finishedAt = utc_now()
        await store.update_run(run)
        RUNS_COMPLETED.labels(status="failed").inc()
    elif payload.type == "run_started":
        run.status = "running"
        if not run.startedAt:
            run.startedAt = utc_now()
        await store.update_run(run)
    elif payload.type == "run_awaiting_review":
        run.status = "awaiting_review"
        if not run.startedAt:
            run.startedAt = utc_now()
        await store.update_run(run)
    elif payload.type == "signal_received":
        signal = str(payload.payload.get("signal", ""))
        if signal == "approved":
            run.status = "running"
        elif signal == "rejected":
            run.status = "rejected"
            run.finishedAt = utc_now()
        elif signal == "timeout":
            run.status = "escalated"
            run.finishedAt = utc_now()
        await store.update_run(run)
        RUNS_COMPLETED.labels(status=run.status).inc()
    return event


@app.get("/internal/runs/{run_id}/secrets/{secret_name}")
async def resolve_internal_secret(
    run_id: str,
    secret_name: str,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, str]:
    """Resolve a project secret by name for a worker mid-run (fix XF-01).

    Guarded by the internal token set; values are served only to holders of a
    valid internal identity and never persisted by the caller.
    """
    require_internal_token(x_internal_token)
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    project_id = run.projectId
    if not project_id:
        raise HTTPException(status_code=409, detail=f"Run {run_id} has no project scope")
    value = await store.get_project_secret(project_id, secret_name)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Secret {secret_name} not found")
    return {"name": secret_name, "value": value}


@app.get("/internal/workflows/{workflow_id}")
async def get_internal_workflow(
    workflow_id: str,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Serve a stored workflow definition to workers (docs 06 XU-3).

    The xflows.load_workflow activity fetches the definition at run time for
    SubWorkflow nodes that reference another workflow by id. Guarded by the
    internal token set.
    """
    require_internal_token(x_internal_token)
    workflow = await store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    if workflow.status == "archived":
        raise HTTPException(status_code=409, detail=f"Workflow {workflow_id} is archived")
    return {"id": workflow.id, "definition": workflow.model_dump(mode="json")}


# --- HITL approval endpoints (docs 06 XU-5, 04 §5) ---
async def _record_approval_signal(
    run_id: str,
    signal_name: str,
    payload: ApprovalDecisionRequest,
    caller: Caller,
) -> dict[str, Any]:
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status != "awaiting_review":
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} is not awaiting review (status: {run.status})",
        )
    node_id = str(payload.evidence.get("nodeId", "") or "")
    signal_payload = {
        "nodeId": node_id,
        "reviewer": payload.reviewer or caller.name,
        "comment": payload.comment or "",
        "evidence": payload.evidence,
    }
    result = await temporal_gateway.signal_workflow(
        f"{run.workflowId}:{run_id}", signal_name, signal_payload
    )
    if not result.connected:
        raise HTTPException(
            status_code=503, detail=f"Temporal unavailable: {result.reason}"
        )
    event = await emit_event(
        run_id,
        "signal_received",
        node_id=node_id or None,
        payload={
            "signal": signal_name,
            "reviewer": signal_payload["reviewer"],
            "comment": signal_payload["comment"],
            "evidence": payload.evidence,
        },
        trace_id=run.traceId,
        event_key=f"approval:{run_id}:{signal_name}",
    )
    return {"eventId": event.id, "signal": signal_name}


@app.post("/runs/{run_id}/approve")
async def approve_run(
    run_id: str, payload: ApprovalDecisionRequest, caller: Caller = Depends(caller_dependency)
) -> dict[str, Any]:
    require_role(caller, "reviewer")
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    require_project_access(caller, run.projectId)
    result = await _record_approval_signal(run_id, "approve", payload, caller)
    return {"status": "signal_sent", **result}


@app.post("/runs/{run_id}/reject")
async def reject_run(
    run_id: str, payload: ApprovalDecisionRequest, caller: Caller = Depends(caller_dependency)
) -> dict[str, Any]:
    require_role(caller, "reviewer")
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    require_project_access(caller, run.projectId)
    if not payload.comment:
        raise HTTPException(status_code=422, detail="A comment is mandatory when rejecting")
    result = await _record_approval_signal(run_id, "reject", payload, caller)
    return {"status": "signal_sent", **result}


@app.post("/runs/{run_id}/request-changes")
async def request_changes_run(
    run_id: str, payload: ApprovalDecisionRequest, caller: Caller = Depends(caller_dependency)
) -> dict[str, Any]:
    require_role(caller, "reviewer")
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    require_project_access(caller, run.projectId)
    result = await _record_approval_signal(run_id, "request_changes", payload, caller)
    return {"status": "signal_sent", **result}


# --- Webhook trigger receiver (docs 06 XU-8) ---
@app.post("/webhooks/{trigger_id}")
async def webhook_receiver(trigger_id: str, request: Request) -> dict[str, Any]:
    trigger = await store.get_trigger(trigger_id)
    if not trigger or trigger.type != "webhook" or not trigger.enabled:
        raise HTTPException(status_code=404, detail=f"Webhook trigger {trigger_id} not found")
    body = await request.body()
    secret = str(trigger.config.get("signatureSecret", ""))
    if secret:
        provided = str(
            request.headers.get("x-webhook-signature", "")
        ).removeprefix("sha256=")
        if not hmac.compare_digest(webhook_signature(secret, body), provided):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
    delivery_id = (
        request.headers.get("x-delivery-id")
        or hashlib.sha256(body).hexdigest()
    )
    workflow_id = str(trigger.config.get("workflowId", ""))
    if not workflow_id:
        raise HTTPException(status_code=409, detail="Webhook trigger has no workflowId configured")
    idempotency_key = f"webhook:{trigger_id}:{delivery_id}"
    run = await _create_run_impl(
        workflow_id,
        RunRequest(
            input=str(trigger.config.get("input", body.decode("utf-8", errors="replace"))),
            idempotencyKey=idempotency_key,
            entryNodeId=trigger.config.get("nodeId"),
            metadata={"triggerId": trigger_id, "deliveryId": delivery_id},
        ),
        project_id=trigger.projectId,
    )
    return {"runId": run.id, "status": run.status}


# --- XWS event trigger receiver: SigV4-signed deliveries from XWS services ---
@app.post("/events/{trigger_id}")
async def event_receiver(trigger_id: str, request: Request) -> dict[str, Any]:
    trigger = await store.get_trigger(trigger_id)
    if not trigger or trigger.type != "event" or not trigger.enabled:
        raise HTTPException(status_code=404, detail=f"Event trigger {trigger_id} not found")
    body = await request.body()
    auth_header = request.headers.get("authorization", "")
    try:
        access_key_id = parse_auth_header(auth_header)["access_key"] if auth_header else ""
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid Authorization header")
    if not access_key_id or access_key_id != trigger.config.get("accessKeyId"):
        raise HTTPException(status_code=403, detail="Unknown access key")
    try:
        await verify_request(request, str(trigger.config.get("secretAccessKey", "")), body)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    delivery_id = (
        request.headers.get("x-delivery-id")
        or hashlib.sha256(body).hexdigest()
    )
    workflow_id = str(trigger.config.get("workflowId", ""))
    if not workflow_id:
        raise HTTPException(status_code=409, detail="Event trigger has no workflowId configured")
    idempotency_key = f"event:{trigger_id}:{delivery_id}"
    run = await _create_run_impl(
        workflow_id,
        RunRequest(
            input=body.decode("utf-8", errors="replace"),
            idempotencyKey=idempotency_key,
            entryNodeId=trigger.config.get("nodeId"),
            metadata={"triggerId": trigger_id, "deliveryId": delivery_id, "source": "xws-event"},
        ),
        project_id=trigger.projectId,
    )
    return {"runId": run.id, "status": run.status}


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
