from __future__ import annotations

from typing import Any

import httpx
from prometheus_client import Counter, Histogram
from temporalio import activity

from xflows_engine import create_default_registry
from xflows_engine.context import NodeExecutionContext, scoped_runtime_config

from .config import settings
from .provider_router import LiteLLMRouter
from .tracing import LangfuseTracer, TracingContext
from .xws import CredentialVendor, ExponentialRetry, XWSClient

router = LiteLLMRouter()
tracer = LangfuseTracer()
registry = create_default_registry()
NODE_EXECUTIONS = Counter("xflows_node_executions_total", "Total node executions", ["component", "status"])
NODE_EXECUTION_LATENCY = Histogram("xflows_node_execution_seconds", "Node execution duration", ["component"])

_XWS_CLIENTS: dict[str, XWSClient] = {}
_XWS_CLIENT_CACHE_MAX = 128
# (run_id, secret_name) -> resolved secret value. Values are fetched from the
# API per run and never written back into configs, runs, or events (XF-01).
_SECRET_CACHE: dict[tuple[str, str], str] = {}


async def _resolve_secret_refs(node_config: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Replace ``<name>Ref`` keys with concrete secret values fetched from the API.

    Project configs hold secret *names* only; the worker resolves them at
    execution time via an internal, token-guarded endpoint and caches the
    values per (run_id, name) in memory only.
    """
    resolved = dict(node_config)
    ref_keys = [key for key in resolved if key.endswith("Ref") and isinstance(resolved[key], str)]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for ref_key in ref_keys:
            secret_name = resolved[ref_key]
            cache_key = (run_id, secret_name)
            cached = _SECRET_CACHE.get(cache_key)
            if cached is not None:
                resolved[ref_key[:-3]] = cached
                resolved.pop(ref_key)
                continue
            headers = {"Content-Type": "application/json"}
            if settings.internal_api_token:
                headers["x-internal-token"] = settings.internal_api_token
            try:
                response = await client.get(
                    f"{settings.api_base_url}/internal/runs/{run_id}/secrets/{secret_name}",
                    headers=headers,
                )
                if response.status_code != 200:
                    raise RuntimeError(f"secret fetch returned HTTP {response.status_code}")
                value = str(response.json().get("value", ""))
            except Exception as error:
                activity.logger.warning(
                    "Failed to resolve secret %r for run %s (best-effort): %s",
                    secret_name, run_id, error,
                )
                continue
            if len(_SECRET_CACHE) > 512:
                _SECRET_CACHE.clear()
            _SECRET_CACHE[cache_key] = value
            resolved[ref_key[:-3]] = value
            resolved.pop(ref_key)
    return resolved


def _build_xws_client(run_id: str) -> XWSClient | None:
    """Build (or reuse) the per-run SigV4 client for XWS tool calls.

    Credentials are vended lazily per (run_id, toolClass) by the embedded
    ``CredentialVendor`` (backbone fix A11/G-5: no static service keys on
    tool requests). Returns None when XWS is not configured so non-XWS
    nodes keep working; XWS tool nodes then fail closed with a clear
    RuntimeError from the executor.
    """
    if not settings.xws_ready:
        return None
    client = _XWS_CLIENTS.get(run_id)
    if client is not None:
        return client
    vendor = CredentialVendor(
        iam_endpoint=settings.xws_iam_endpoint,
        access_key_id=settings.xws_access_key_id,
        secret_access_key=settings.xws_secret_access_key,
        region=settings.xws_region,
        service=settings.xws_service,
        role_arns=settings.xws_role_arn_map,
        session_duration_s=settings.xws_session_duration_s,
    )
    client = XWSClient(
        base_url=settings.xws_base_url,
        region=settings.xws_region,
        service=settings.xws_service,
        vendor=vendor,
        retry=ExponentialRetry(),
    )
    if len(_XWS_CLIENTS) >= _XWS_CLIENT_CACHE_MAX:
        _XWS_CLIENTS.clear()
    _XWS_CLIENTS[run_id] = client
    return client


async def publish_event(
    run_id: str,
    event_type: str,
    *,
    node_id: str | None = None,
    payload: dict[str, Any] | None = None,
    trace_id: str | None = None,
    event_key: str | None = None,
) -> None:
    headers = {"Content-Type": "application/json"}
    if settings.internal_api_token:
        headers["x-internal-token"] = settings.internal_api_token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.api_base_url}/internal/runs/{run_id}/events",
                headers=headers,
                json={
                    "type": event_type,
                    "nodeId": node_id,
                    "payload": payload or {},
                    "traceId": trace_id,
                    "eventKey": event_key,
                },
            )
    except Exception as error:
        activity.logger.warning(
            "Failed to publish event %s for run %s (best-effort): %s", event_type, run_id, error
        )


@activity.defn(name="xflows.record_node_statuses")
async def record_node_statuses(
    run_id: str,
    trace_id: str,
    statuses: dict[str, str],
) -> dict[str, Any]:
    attempt = activity.info().attempt if activity.is_local() else 1
    for node_id, status in statuses.items():
        if status == "skipped":
            event_type = "node_skipped"
        elif status == "failed_routed":
            event_type = "node_routed_to_error"
        else:
            continue
        await publish_event(
            run_id,
            event_type,
            node_id=node_id,
            payload={"status": status},
            trace_id=trace_id,
            event_key=f"{run_id}:{node_id}:{event_type}:{attempt}",
        )
    return {"recorded": len(statuses)}


@activity.defn(name="xflows.execute_node")
async def execute_node(
    node: dict[str, Any],
    input_value: dict[str, Any],
    run_id: str,
    trace_id: str,
    runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    component_id = node.get("componentId")
    node_id = node.get("id", "unknown")
    runtime_config = runtime_config or {}
    node_config = scoped_runtime_config(str(component_id or ""), runtime_config)
    node_config = await _resolve_secret_refs(node_config, run_id)

    async def llm_chat(
        prompt: str,
        system_prompt: str | None,
        model_hint: str | None,
        temperature: float,
        **options: Any,
    ) -> dict[str, Any]:
        return await router.chat(
            prompt,
            system_prompt,
            model_hint,
            temperature,
            runtime_config=node_config,
            **options,
        )

    context = NodeExecutionContext(
        run_id=run_id,
        trace_id=trace_id,
        user_input=str(input_value.get("value", "")),
        llm_chat=llm_chat,
        http_request=_http_request,
        runtime_config=node_config,
        xws_client=_build_xws_client(run_id),
    )

    trace_ctx = TracingContext(trace_id=trace_id, run_id=run_id)
    attempt = activity.info().attempt
    with NODE_EXECUTION_LATENCY.labels(component=component_id).time():
        try:
            await publish_event(
                run_id,
                "node_started",
                node_id=node_id,
                trace_id=trace_id,
                event_key=f"{run_id}:{node_id}:node_started:{attempt}",
            )
            async with tracer.span(trace_ctx, f"node:{component_id}", {"nodeId": node_id, "input": input_value}):
                result = await registry.dispatch(node=node, input_payload=input_value, context=context)

                NODE_EXECUTIONS.labels(component=component_id, status="success").inc()
                await publish_event(
                    run_id,
                    "node_succeeded",
                    node_id=node_id,
                    payload={
                        "output": result.get("value"),
                        "metadata": {k: v for k, v in result.items() if k != "value"},
                        "attempt": attempt,
                    },
                    trace_id=trace_id,
                    event_key=f"{run_id}:{node_id}:node_succeeded:{attempt}",
                )
                return result
        except Exception as error:
            NODE_EXECUTIONS.labels(component=component_id, status="error").inc()
            await publish_event(
                run_id,
                "node_failed",
                node_id=node_id,
                payload={"error": str(error), "attempt": attempt},
                trace_id=trace_id,
            )
            raise


async def _http_request(method: str, url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url)
        response.raise_for_status()
        return response.text


@activity.defn(name="xflows.load_workflow")
async def load_workflow(workflow_id: str) -> dict[str, Any]:
    """Fetch a stored workflow definition from the API by id (XU-3).

    Used by SubWorkflow nodes that reference another workflow by id rather
    than embedding its definition inline. The API serves the stored
    definition from its token-guarded internal endpoint.
    """
    headers = {"Content-Type": "application/json"}
    if settings.internal_api_token:
        headers["x-internal-token"] = settings.internal_api_token
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{settings.api_base_url}/internal/workflows/{workflow_id}",
            headers=headers,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"workflow {workflow_id!r} fetch returned HTTP {response.status_code}"
        )
    payload = response.json()
    definition = payload.get("definition") if isinstance(payload, dict) else None
    if isinstance(definition, dict):
        return definition
    if isinstance(payload, dict) and "nodes" in payload:
        return payload
    raise RuntimeError(f"workflow {workflow_id!r} response contained no definition")


@activity.defn(name="xflows.complete_run")
async def complete_run(run_id: str, trace_id: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_type = "run_succeeded" if status == "succeeded" else "run_failed"
    await publish_event(run_id, event_type, payload=payload, trace_id=trace_id)
    _XWS_CLIENTS.pop(run_id, None)
    return {"ok": True}


@activity.defn(name="xflows.prepare_approval")
async def prepare_approval(
    node: dict[str, Any],
    input_value: dict[str, Any],
    run_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Record the parked state, notify the reviewer via relay, return the request."""
    params = node.get("params", {}) or {}
    node_id = str(node.get("id", ""))
    try:
        timeout_s = int(params.get("signalTimeoutS", 259_200))
    except (TypeError, ValueError):
        timeout_s = 259_200
    timeout_s = max(1, min(timeout_s, 30 * 86_400))
    summary = str(params.get("summary") or input_value.get("value") or "")[:200]
    evidence = params.get("evidence") if isinstance(params.get("evidence"), dict) else {}
    notify = params.get("notify") if isinstance(params.get("notify"), dict) else {}

    request = {
        "runId": run_id,
        "nodeId": node_id,
        "summary": summary,
        "evidence": evidence,
        "notify": notify,
        "signalTimeoutS": timeout_s,
    }
    await publish_event(
        run_id,
        "run_awaiting_review",
        node_id=node_id,
        payload={"summary": summary, "signalTimeoutS": timeout_s},
        trace_id=trace_id,
        event_key=f"{run_id}:{node_id}:run_awaiting_review",
    )

    channel = str(notify.get("channel", "console")) if notify else "console"
    deep_link = str(notify.get("deepLink") or f"{settings.api_base_url}/runs/{run_id}")
    client = _build_xws_client(run_id)
    if client is not None and (notify or summary):
        try:
            client.request(
                method="POST",
                path="/relay/notify",
                tool_class="relay",
                run_id=run_id,
                json_body={
                    "message": summary or f"Run {run_id} awaits review",
                    "deepLink": deep_link,
                    "channel": channel,
                    "card": {"title": "Approval needed", "runId": run_id},
                },
            )
        except Exception as error:  # noqa: BLE001 — notify is best-effort
            activity.logger.warning(
                "Relay notify failed for run %s (best-effort): %s", run_id, error
            )
    return request


@activity.defn(name="xflows.record_approval")
async def record_approval(
    run_id: str,
    trace_id: str,
    node_id: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    decision = decision if isinstance(decision, dict) else {"decision": str(decision)}
    await publish_event(
        run_id,
        "signal_received",
        node_id=node_id,
        payload={
            "signal": decision.get("decision", "timeout"),
            "reviewer": decision.get("reviewer", ""),
            "comment": decision.get("comment", ""),
            "evidence": decision.get("evidence", {}),
        },
        trace_id=trace_id,
        event_key=f"{run_id}:{node_id}:signal_received",
    )
    return {"ok": True}
