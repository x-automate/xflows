from __future__ import annotations

from typing import Any

import httpx
from prometheus_client import Counter, Histogram
from temporalio import activity

from .config import settings
from .nodes import create_default_registry
from .nodes.context import NodeExecutionContext
from .provider_router import LiteLLMRouter
from .tracing import LangfuseTracer, TracingContext

router = LiteLLMRouter()
tracer = LangfuseTracer()
registry = create_default_registry()
NODE_EXECUTIONS = Counter("xflows_node_executions_total", "Total node executions", ["component", "status"])
NODE_EXECUTION_LATENCY = Histogram("xflows_node_execution_seconds", "Node execution duration", ["component"])


async def publish_event(
    run_id: str,
    event_type: str,
    *,
    node_id: str | None = None,
    payload: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    headers = {"Content-Type": "application/json"}
    if settings.internal_api_token:
        headers["x-internal-token"] = settings.internal_api_token
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{settings.api_base_url}/internal/runs/{run_id}/events",
            headers=headers,
            json={
                "type": event_type,
                "nodeId": node_id,
                "payload": payload or {},
                "traceId": trace_id,
            },
        )


@activity.defn(name="xflows.execute_node")
async def execute_node(
    node: dict[str, Any],
    input_value: dict[str, Any],
    run_id: str,
    trace_id: str,
) -> dict[str, Any]:
    component_id = node.get("componentId")
    node_id = node.get("id", "unknown")
    context = NodeExecutionContext(
        run_id=run_id,
        trace_id=trace_id,
        user_input=str(input_value.get("value", "")),
        llm_chat=router.chat,
        http_request=_http_request,
    )

    trace_ctx = TracingContext(trace_id=trace_id, run_id=run_id)
    with NODE_EXECUTION_LATENCY.labels(component=component_id).time():
        try:
            await publish_event(run_id, "node_started", node_id=node_id, trace_id=trace_id)
            async with tracer.span(trace_ctx, f"node:{component_id}", {"nodeId": node_id, "input": input_value}):
                result = await registry.dispatch(node=node, input_payload=input_value, context=context)

                NODE_EXECUTIONS.labels(component=component_id, status="success").inc()
                await publish_event(
                    run_id,
                    "node_succeeded",
                    node_id=node_id,
                    payload={"output": result.get("value")},
                    trace_id=trace_id,
                )
                return result
        except Exception as error:
            NODE_EXECUTIONS.labels(component=component_id, status="error").inc()
            await publish_event(
                run_id,
                "node_failed",
                node_id=node_id,
                payload={"error": str(error)},
                trace_id=trace_id,
            )
            raise


async def _http_request(method: str, url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url)
        response.raise_for_status()
        return response.text


@activity.defn(name="xflows.complete_run")
async def complete_run(run_id: str, trace_id: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_type = "run_succeeded" if status == "succeeded" else "run_failed"
    await publish_event(run_id, event_type, payload=payload, trace_id=trace_id)
    return {"ok": True}
