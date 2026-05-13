from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult


class LiteLlmExecutor(BaseNodeExecutor):
    component_ids = ("LiteLLM",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        runtime_config = context.runtime_config or {}
        model_hint = (
            str(params.get("model"))
            if params.get("model") is not None
            else (
                str(runtime_config.get("litellmModel"))
                if runtime_config.get("litellmModel") is not None
                else None
            )
        )
        temperature = float(params.get("temperature", runtime_config.get("temperature", 0.2)))
        content = await context.llm_chat(
            str(input_payload.get("value", "")),
            input_payload.get("system") if isinstance(input_payload.get("system"), str) else None,
            model_hint,
            temperature,
        )
        metadata = {
            "provider": "litellm",
            "model": model_hint,
            "apiBase": params.get("apiBase") or runtime_config.get("litellmBaseUrl"),
        }
        return NodeExecutionResult(value=content, metadata=metadata)


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
