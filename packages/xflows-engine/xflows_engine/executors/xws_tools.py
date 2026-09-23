"""XWS tool node executors (Wave 3, docs 06 XU-2).

Five tool classes are wired end-to-end in v1 (S3, Lambda invoke,
IAM evaluate, Relay notify, GatewayLLM); the remaining three
(DmsIntrospect, ApigwRegister, Audit) are registered but inert until
their backbone services ship. All calls flow through the
``context.xws_client`` seam so the engine itself never touches httpx
or credentials.
"""

from __future__ import annotations

import json
from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult
from ..schema_validation import parse_json_output, parse_schema, validate_against_schema


class XwsToolExecutor(BaseNodeExecutor):
    """Shared plumbing: resolve toolClass + xws_client, then issue a call."""

    component_ids: tuple[str, ...] = ()
    default_tool_class: str = ""

    def _client(self, context: NodeExecutionContext):
        client = context.xws_client
        if client is None:
            raise RuntimeError(
                f"{type(self).__name__} requires an xws_client on the execution "
                "context (inject from workers layer)"
            )
        return client

    def _tool_class(self, node: dict[str, Any]) -> str:
        params = node.get("params", {}) or {}
        return str(params.get("toolClass", self.default_tool_class))


class XWS3Executor(XwsToolExecutor):
    """S3 artifact storage against bucket ``apigen-artifacts`` (retry 5x)."""

    component_ids = ("XWSS3",)
    default_tool_class = "s3"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        client = self._client(context)
        tool_class = self._tool_class(node)
        operation = str(params.get("operation", "put")).lower()
        key = str(params.get("key") or input_payload.get("key") or "")
        if not key:
            raise ValueError("XWSS3 requires a 'key' param or input 'key' field")
        body = params.get("body", input_payload.get("value"))
        bucket = str(params.get("bucket", "apigen-artifacts"))

        if operation == "put":
            result = client.request(
                method="PUT",
                path=f"/s3/{bucket}/{key}",
                tool_class=tool_class,
                run_id=context.run_id,
                json_body={"body": body},
                retry=True,
            )
        elif operation == "get":
            result = client.request(
                method="GET",
                path=f"/s3/{bucket}/{key}",
                tool_class=tool_class,
                run_id=context.run_id,
                retry=True,
            )
        elif operation in ("list_versions", "list-versions"):
            result = client.request(
                method="GET",
                path=f"/s3/{bucket}/{key}",
                tool_class=tool_class,
                run_id=context.run_id,
                params={"versions": "true"},
                retry=True,
            )
        else:
            raise ValueError(f"unsupported XWSS3 operation {operation!r}")

        return NodeExecutionResult(
            value=result.get("value", result),
            metadata={
                "xwsTool": "XWSS3",
                "operation": operation,
                "key": key,
                "toolClass": tool_class,
            },
        )


class XWSLambdaInvokeExecutor(XwsToolExecutor):
    """Lambda invocation with an Idempotency-Key derived from the bundle hash."""

    component_ids = ("XWSLambdaInvoke",)
    default_tool_class = "lambda"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        client = self._client(context)
        tool_class = self._tool_class(node)
        function_name = str(params.get("functionName", ""))
        if not function_name:
            raise ValueError("XWSLambdaInvoke requires a 'functionName' param")
        bundle_hash = str(
            params.get("bundleHash") or input_payload.get("bundleHash") or ""
        )
        if not bundle_hash:
            raise ValueError(
                "XWSLambdaInvoke requires 'bundleHash' (param or input) for idempotency"
            )
        payload = params.get("payload", input_payload.get("value"))

        result = client.request(
            method="POST",
            path=f"/lambda/invoke/{function_name}",
            tool_class=tool_class,
            run_id=context.run_id,
            json_body={"payload": payload, "bundleHash": bundle_hash},
            idempotency_key=f"bundle-{bundle_hash}",
        )
        return NodeExecutionResult(
            value=result.get("value", result),
            metadata={
                "xwsTool": "XWSLambdaInvoke",
                "functionName": function_name,
                "bundleHash": bundle_hash,
                "toolClass": tool_class,
            },
        )


class XWSIAMEvaluateExecutor(XwsToolExecutor):
    """Policy evaluation via iam-svc ``POST /iam/evaluate`` (fail closed)."""

    component_ids = ("XWSIAMEvaluate",)
    default_tool_class = "iam"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        client = self._client(context)
        tool_class = self._tool_class(node)
        principal = str(params.get("principal") or input_payload.get("principal") or "")
        action = str(params.get("action") or input_payload.get("action") or "")
        resource = str(params.get("resource") or input_payload.get("resource") or "")
        if not (principal and action and resource):
            raise ValueError(
                "XWSIAMEvaluate requires 'principal', 'action' and 'resource'"
            )

        result = client.request(
            method="POST",
            path="/iam/evaluate",
            tool_class=tool_class,
            run_id=context.run_id,
            json_body={
                "principal": principal,
                "action": action,
                "resource": resource,
                "context": params.get("context", {}),
            },
        )
        allowed = bool(result.get("allowed", False))
        # Fail closed: an absent/ambiguous decision denies access.
        return NodeExecutionResult(
            value=allowed,
            metadata={
                "xwsTool": "XWSIAMEvaluate",
                "allowed": allowed,
                "decision": result.get("decision", "deny"),
                "toolClass": tool_class,
            },
        )


class XWSRelayNotifyExecutor(XwsToolExecutor):
    """Approval notifications (docs 05 §7). Best-effort: failure parks the gate."""

    component_ids = ("XWSRelayNotify",)
    default_tool_class = "relay"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        tool_class = self._tool_class(node)
        message = str(params.get("message") or input_payload.get("value") or "")
        deep_link = str(params.get("deepLink") or input_payload.get("deepLink") or "")
        channel = str(params.get("channel", "console"))

        client = self._client(context)
        try:
            result = client.request(
                method="POST",
                path="/relay/notify",
                tool_class=tool_class,
                run_id=context.run_id,
                json_body={
                    "message": message,
                    "deepLink": deep_link,
                    "channel": channel,
                    "card": params.get("card", {"title": message[:80]}),
                },
            )
        except Exception as exc:  # noqa: BLE001 — notify is best-effort
            return NodeExecutionResult(
                value={"notified": False, "parked": True, "error": str(exc)},
                metadata={
                    "xwsTool": "XWSRelayNotify",
                    "notified": False,
                    "parked": True,
                    "toolClass": tool_class,
                },
            )
        return NodeExecutionResult(
            value={
                "notified": True,
                "parked": False,
                "notificationId": result.get("notificationId"),
            },
            metadata={
                "xwsTool": "XWSRelayNotify",
                "notified": True,
                "parked": False,
                "toolClass": tool_class,
            },
        )


class XWSGatewayLLMExecutor(XwsToolExecutor):
    """Structured LLM outputs via the XWS Model Gateway (docs 05 §7, 06 XU-4).

    Every prompt routes through ``POST /v1/gateway/complete`` (single LLM
    egress, token metering). 429s back off via the client seam's retry
    flag; a primary+fallback failure surfaces as a stage failure so the
    stage retry policy (<=2) applies upstream. When ``outputSchema`` is
    provided the gateway receives a strict json_schema response format
    and the parsed response is re-validated locally before succeeding.
    """

    component_ids = ("XWSGatewayLLM",)
    default_tool_class = "llm"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        client = self._client(context)
        tool_class = self._tool_class(node)

        prompt = params.get("prompt", input_payload.get("value"))
        if isinstance(prompt, (dict, list)):
            prompt = json.dumps(prompt)
        prompt = str(prompt) if prompt is not None else ""
        if not prompt.strip():
            raise ValueError("XWSGatewayLLM requires a 'prompt' param or input 'value'")

        body: dict[str, Any] = {"prompt": prompt}
        system = params.get("system") or input_payload.get("system")
        if isinstance(system, str) and system.strip():
            body["system"] = system
        model = params.get("model") or (context.runtime_config or {}).get("litellmModel")
        if model is not None:
            body["model"] = str(model)
        temperature = params.get("temperature")
        if temperature is not None:
            body["temperature"] = float(temperature)
        max_tokens = params.get("maxTokens", params.get("max_tokens"))
        if max_tokens:
            try:
                body["maxTokens"] = int(max_tokens)
            except (TypeError, ValueError):
                pass

        schema = None
        schema_raw = params.get("outputSchema")
        if schema_raw is not None and str(schema_raw).strip() != "":
            schema = parse_schema(schema_raw)
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": schema},
            }

        result = client.request(
            method="POST",
            path="/v1/gateway/complete",
            tool_class=tool_class,
            run_id=context.run_id,
            json_body=body,
            retry=True,
        )

        content = result.get("content", result.get("value", result))
        metadata = {
            "xwsTool": "XWSGatewayLLM",
            "model": result.get("model") or body.get("model"),
            "usage": result.get("usage", {}),
            "toolClass": tool_class,
        }

        if schema is None:
            return NodeExecutionResult(value=content, metadata=metadata)

        parsed, parse_error = parse_json_output(str(content))
        if parse_error:
            raise ValueError(f"gateway response is not valid JSON: {parse_error}")
        errors = validate_against_schema(parsed, schema)
        if errors:
            raise ValueError(
                f"gateway response failed schema validation: {errors[0]}"
            )
        metadata["schemaValidated"] = True
        return NodeExecutionResult(value=parsed, metadata=metadata)


class XWSDmsIntrospectExecutor(XwsToolExecutor):
    """Read-only DMS introspection — inert in v1."""

    component_ids = ("XWSDmsIntrospect",)
    default_tool_class = "dms-ro"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        raise NotImplementedError("XWSDmsIntrospect is not implemented in v1")


class XWSApigwRegisterExecutor(XwsToolExecutor):
    """API gateway route registration / key issuance / rollback — inert in v1."""

    component_ids = ("XWSApigwRegister",)
    default_tool_class = "apigw"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        raise NotImplementedError("XWSApigwRegister is not implemented in v1")


class XWSAuditExecutor(XwsToolExecutor):
    """Immutable audit append (docs 05 §4) — inert in v1."""

    component_ids = ("XWSAudit",)
    default_tool_class = "audit"

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        raise NotImplementedError("XWSAudit is not implemented in v1")
