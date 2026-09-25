from __future__ import annotations

import json
from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult


class WebhookTriggerExecutor(BaseNodeExecutor):
    component_ids = ("Webhook", "WebhookTrigger")

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        value = input_payload.get("value", context.user_input)
        metadata = {
            "trigger": "webhook",
            "webhook": {
                "path": params.get("path", "/webhook"),
                "method": str(params.get("method", "POST")).upper(),
                "secretHeader": params.get("secretHeader", "x-webhook-secret"),
            },
        }
        return NodeExecutionResult(value=value, metadata=metadata)


class XWSEventTriggerExecutor(BaseNodeExecutor):
    component_ids = ("XWSEventTrigger",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        value = input_payload.get("value", context.user_input)
        metadata = {
            "trigger": "xws-event",
            "xwsEvent": {
                "sourceService": params.get("sourceService", ""),
                "eventType": params.get("eventType", ""),
            },
        }
        return NodeExecutionResult(value=value, metadata=metadata)


_LOG_LEVELS = ("debug", "info", "warn", "error")


class TraceLogExecutor(BaseNodeExecutor):
    component_ids = ("TraceLog",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        message = str(params.get("message") or input_payload.get("value") or "")
        level = str(params.get("level", "info")).lower()
        if level not in _LOG_LEVELS:
            level = "info"
        fields_raw = params.get("fields", {})
        if isinstance(fields_raw, str):
            try:
                fields = json.loads(fields_raw) if fields_raw.strip() else {}
            except ValueError:
                fields = {"raw": fields_raw}
        elif isinstance(fields_raw, dict):
            fields = fields_raw
        else:
            fields = {}
        metadata = {
            "trace": {
                "level": level,
                "message": message,
                "fields": fields,
                "nodeId": str(node.get("id", "")),
            }
        }
        return NodeExecutionResult(value=input_payload.get("value", ""), metadata=metadata)


def _parse_fields(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    return {}


class ErrorLogExecutor(BaseNodeExecutor):
    """Terminus for a red error edge: record the failure, keep the run readable.

    The engine delivers an error edge as ``{"value": "", "error": {...}}`` — the
    blank value is why a plain ``PromptTemplate`` on an error branch renders
    nothing useful. This node reads that envelope, emits a structured log under
    ``errorLog`` metadata (so it lands in the run's ``node_succeeded`` payload
    and shows up in the Logs tab), and returns the formatted message as its
    value, so whatever follows on the branch has real text to work with.

    Wired to a node's *data* output instead it degrades sensibly: there is no
    error envelope, so it logs the incoming value and passes it through.
    """

    component_ids = ("ErrorLog",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        level = str(params.get("level", "error")).lower()
        if level not in _LOG_LEVELS:
            level = "error"

        error = input_payload.get("error")
        error = error if isinstance(error, dict) else {}
        failed_node = str(error.get("nodeId") or "")
        failed_component = str(error.get("componentId") or "")
        reason = str(error.get("message") or "")

        if reason:
            origin = f"{failed_component or 'node'} ({failed_node})" if failed_node else "upstream node"
            summary = f"{origin} failed: {reason}"
        else:
            # Not on an error branch — nothing failed, just log what came through.
            summary = str(input_payload.get("value", ""))

        prefix = str(params.get("message") or "").strip()
        if prefix:
            summary = f"{prefix}: {summary}" if summary else prefix

        entry: dict[str, Any] = {
            "level": level,
            "message": summary,
            "nodeId": str(node.get("id", "")),
            "runId": context.run_id,
            "fields": _parse_fields(params.get("fields", {})),
        }
        if error:
            entry["failedNodeId"] = failed_node
            entry["failedComponentId"] = failed_component
            entry["reason"] = reason
        if str(params.get("includeInput", "false")).lower() == "true":
            entry["input"] = input_payload.get("value", "")

        metadata: dict[str, Any] = {"errorLog": entry, "trace": entry}

        # Logging a failure does not by itself mean the run recovered. `rethrow`
        # records the entry and then re-raises, so the run still fails loudly —
        # for branches that exist to report, not to recover.
        if str(params.get("rethrow", "false")).lower() == "true" and error:
            raise RuntimeError(summary)

        return NodeExecutionResult(value=summary, metadata=metadata)


class ApiCallerExecutor(BaseNodeExecutor):
    component_ids = ("ApiCaller", "ApiCall")

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", ""))
        if not url:
            raise ValueError("ApiCaller requires a URL")
        response_text = await context.http_request(method, url)
        return NodeExecutionResult(value=response_text, metadata={"status": "ok", "method": method, "url": url})


class LangfuseTracerExecutor(BaseNodeExecutor):
    component_ids = ("LangfuseTracer",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        metadata = {
            "traceProvider": "langfuse",
            "traceConfig": {
                "host": params.get("host"),
                "publicKey": params.get("publicKey"),
                "tags": params.get("tags", []),
            },
        }
        return NodeExecutionResult(value=input_payload.get("value", ""), metadata=metadata)


class LangsmithTracerExecutor(BaseNodeExecutor):
    component_ids = ("LangsmithTracer",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        metadata = {
            "traceProvider": "langsmith",
            "traceConfig": {
                "endpoint": params.get("endpoint"),
                "project": params.get("project"),
                "tags": params.get("tags", []),
            },
        }
        return NodeExecutionResult(value=input_payload.get("value", ""), metadata=metadata)
