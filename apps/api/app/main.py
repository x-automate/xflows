from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncGenerator
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sse_starlette.sse import EventSourceResponse

from .config import settings
from .nodes import NodeGraphRunner, create_default_registry, normalize_workflow_graph
from .nodes.context import NodeExecutionContext
from .models import (
    InternalRunEventRequest,
    ProjectCreateRequest,
    ProjectRecord,
    ProjectUpdateRequest,
    ProjectRunRequest,
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
from .store import InMemoryStore, utc_now
from .temporal_client import TemporalGateway
from .persistence import create_store
from .store import BaseStore

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
node_registry = create_default_registry()


@app.on_event("startup")
async def startup() -> None:
    global store
    store = await create_store(settings)
    logger.info("Persistence store initialized: %s", settings.persistence_mode)


@app.on_event("shutdown")
async def shutdown() -> None:
    await store.close()


async def emit_event(
    run_id: str,
    event_type: str,
    node_id: str | None = None,
    payload: dict | None = None,
    trace_id: str | None = None,
) -> RunEvent:
    event = RunEvent(
        runId=run_id,
        type=event_type,
        nodeId=node_id,
        payload=payload or {},
        timestamp=utc_now(),
        traceId=trace_id,
    )
    return await store.append_event(event)


def require_internal_token(x_internal_token: str | None) -> None:
    configured = settings.internal_api_token
    if configured and x_internal_token != configured:
        raise HTTPException(status_code=401, detail="Invalid internal token")


async def simulate_local_run(run: RunRecord) -> None:
    raise NotImplementedError("Local simulation is replaced by local execution")


async def run_litellm_chat(
    prompt: str,
    system_prompt: str | None = None,
    model_hint: str | None = None,
    temperature: float = 0.2,
    runtime_config: dict[str, Any] | None = None,
) -> str:
    runtime_config = runtime_config or {}
    model = model_hint or str(runtime_config.get("litellmModel") or settings.litellm_model_alias)
    headers = {"Content-Type": "application/json"}
    auth_key = (
        runtime_config.get("litellmApiKey")
        or settings.litellm_api_key
        or settings.litellm_master_key
    )
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    base_url = str(runtime_config.get("litellmBaseUrl") or settings.litellm_base_url)
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
            response = await client.post("/v1/chat/completions", headers=headers, json=payload)
            if response.status_code < 400:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            body = response.text.strip()
            last_error = (
                f"LiteLLM chat failed (status={response.status_code}, model={candidate_model}): "
                f"{body or response.reason_phrase}"
            )
            break
    raise RuntimeError(last_error)


async def execute_local_run(run: RunRecord, workflow: WorkflowRecord) -> None:
    run.status = "running"
    run.startedAt = run.startedAt or utc_now()
    await store.update_run(run)

    try:
        raw_nodes = [node.model_dump(mode="json") for node in workflow.nodes]
        raw_edges = [edge.model_dump(mode="json") for edge in workflow.edges]
        nodes, edges = normalize_workflow_graph(raw_nodes, raw_edges)
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input=run.input)
        runtime_config = (
            run.metadata.get("runtimeConfig", {})
            if isinstance(run.metadata.get("runtimeConfig"), dict)
            else {}
        )

        async def llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> str:
            return await run_litellm_chat(
                prompt,
                system_prompt,
                model_hint,
                temperature,
                runtime_config=runtime_config,
            )

        context = NodeExecutionContext(
            run_id=run.id,
            trace_id=run.traceId,
            user_input=run.input,
            llm_chat=llm_chat,
            http_request=_http_request,
            runtime_config=runtime_config,
        )

        async def execute(node: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
            node_id = node.get("id", "unknown")
            await emit_event(run.id, "node_started", node_id=node_id, trace_id=run.traceId)
            result = await node_registry.dispatch(node=node, input_payload=input_payload, context=context)
            await emit_event(
                run.id,
                "node_succeeded",
                node_id=node_id,
                payload={
                    "output": result.get("value"),
                    "metadata": {k: v for k, v in result.items() if k != "value"},
                },
                trace_id=run.traceId,
            )
            return result

        outputs, order = await runner.run(execute)

        final_node_id = runner.resolve_output_node_id(order)
        run.status = "succeeded"
        run.output = str(outputs.get(final_node_id, {}).get("value", ""))
        run.finishedAt = utc_now()
        await store.update_run(run)
        RUNS_COMPLETED.labels(status="succeeded").inc()
        await emit_event(
            run.id,
            "run_succeeded",
            payload={"output": run.output},
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
async def create_user(payload: UserCreateRequest) -> UserRecord:
    return await store.create_user(payload)


@app.get("/users", response_model=list[UserRecord])
async def list_users() -> list[UserRecord]:
    return await store.list_users()


@app.get("/users/{user_id}", response_model=UserRecord)
async def get_user(user_id: str) -> UserRecord:
    user = await store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


@app.post("/projects", response_model=ProjectRecord)
async def create_project(payload: ProjectCreateRequest) -> ProjectRecord:
    return await store.create_project(payload)


@app.get("/projects", response_model=list[ProjectRecord])
async def list_projects() -> list[ProjectRecord]:
    return await store.list_projects()


@app.get("/projects/{project_id}", response_model=ProjectRecord)
async def get_project(project_id: str) -> ProjectRecord:
    project = await store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@app.patch("/projects/{project_id}", response_model=ProjectRecord)
async def update_project(project_id: str, payload: ProjectUpdateRequest) -> ProjectRecord:
    project = await store.update_project(project_id, payload)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


@app.get("/projects/{project_id}/triggers", response_model=list[TriggerRecord])
async def list_project_triggers(project_id: str) -> list[TriggerRecord]:
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return await store.list_triggers(project_id)


@app.post("/projects/{project_id}/triggers", response_model=TriggerRecord)
async def create_project_trigger(project_id: str, payload: TriggerCreateRequest) -> TriggerRecord:
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return await store.create_trigger(project_id, payload)


@app.patch("/projects/{project_id}/triggers/{trigger_id}", response_model=TriggerRecord)
async def update_project_trigger(
    project_id: str, trigger_id: str, payload: TriggerUpdateRequest
) -> TriggerRecord:
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    updated = await store.update_trigger(project_id, trigger_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")
    return updated


@app.post("/workflows", response_model=WorkflowRecord)
async def create_workflow(payload: WorkflowCreateRequest) -> WorkflowRecord:
    if await store.get_workflow(payload.id):
        raise HTTPException(status_code=409, detail=f"Workflow {payload.id} already exists")
    return await store.create_workflow(payload)


@app.get("/workflows", response_model=list[WorkflowRecord])
async def list_workflows() -> list[WorkflowRecord]:
    return await store.list_workflows()


@app.post("/workflows/{workflow_id}/runs", response_model=RunRecord)
async def create_run(workflow_id: str, payload: RunRequest) -> RunRecord:
    with RUN_CREATE_LATENCY.time():
        return await _create_run_impl(workflow_id, payload)


@app.post("/projects/{project_id}/runs", response_model=RunRecord)
async def create_project_run(project_id: str, payload: ProjectRunRequest) -> RunRecord:
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
async def list_project_runs(project_id: str) -> list[RunRecord]:
    if not await store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return await store.list_runs(project_id)


async def _create_run_impl(
    workflow_id: str, payload: RunRequest, project_id: str | None = None
) -> RunRecord:
    workflow = await store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

    trace_id = f"trace_{uuid4().hex[:16]}"
    run = await store.create_run(
        workflow_id,
        workflow.version,
        payload.input,
        trace_id=trace_id,
        project_id=project_id,
        metadata=payload.metadata,
        idempotency_key=payload.idempotencyKey,
    )
    RUNS_CREATED.inc()
    await emit_event(run.id, "run_started", trace_id=trace_id)

    temporal_status = await temporal_gateway.start_workflow(
        workflow_name="XFlowsWorkflow.run",
        workflow_id=f"{workflow_id}:{run.id}",
        args=[
            workflow.model_dump(mode="json"),
            run.input,
            run.id,
            trace_id,
            run.metadata.get("runtimeConfig", {}) if isinstance(run.metadata, dict) else {},
        ],
    )

    if temporal_status.connected:
        run.status = "running"
        run.startedAt = utc_now()
        await store.update_run(run)
    else:
        # Execute locally when Temporal is unavailable so test panel shows real outputs.
        asyncio.create_task(execute_local_run(run, workflow))

    return run


@app.get("/runs/{run_id}", response_model=RunRecord)
async def get_run(run_id: str) -> RunRecord:
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@app.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_id: int | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    if not await store.get_run(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

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
async def list_run_events(run_id: str, after_id: int | None = Query(default=None)) -> list[RunEvent]:
    if not await store.get_run(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
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
    )
    if payload.type == "run_succeeded":
        run.status = "succeeded"
        run.output = payload.payload.get("output")
        run.finishedAt = utc_now()
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
    return event


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
