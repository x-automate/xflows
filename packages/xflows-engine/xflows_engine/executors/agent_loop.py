"""Bounded agent loop executor (docs 06 XU-3 / master-plan C3).

Replaces the faked ReAct POC loop with a real, bounded tool-calling loop:
the model must answer with a JSON envelope ``{"action": "tool", ...}`` or
``{"action": "final", "output": ...}``. Every tool call is constrained to
the node's ``allowlist`` of toolClasses and routed through the
``context.xws_client`` seam. Bounds: ``maxIterations`` (default 5),
``tokenCap`` (cumulative usage tokens, default 20000), ``timeoutS``
(default 60). The full transcript is returned in metadata so the workers
layer can persist it to run_events.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult
from ..schema_validation import parse_json_output

AGENT_SYSTEM_PROMPT = (
    "You are a tool-calling agent. Respond ONLY with a JSON object.\n"
    'To call a tool: {"action": "tool", "toolClass": "<class>", "tool": '
    '"<XWSS3|XWSLambdaInvoke|XWSIAMEvaluate|XWSRelayNotify>", "args": {...}}\n'
    'To finish: {"action": "final", "output": "<your answer>"}\n'
    "Available toolClasses: {allowlist}.\n"
    "Observed tool results follow in the conversation."
)

_TOOL_CLASS_BY_TOOL = {
    "XWSS3": "s3",
    "XWSLambdaInvoke": "lambda",
    "XWSIAMEvaluate": "iam",
    "XWSRelayNotify": "relay",
}

# Which arg keys a loop tool call may set per tool; args are passed through
# to the XWS tool path params with these names only.
_ALLOWED_ARG_KEYS = {
    "XWSS3": ("operation", "key", "bucket", "body"),
    "XWSLambdaInvoke": ("functionName", "bundleHash", "payload"),
    "XWSIAMEvaluate": ("principal", "action", "resource", "context"),
    "XWSRelayNotify": ("message", "deepLink", "channel", "card"),
}


def _int_param(params: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _usage_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    # The workers' router normalizes usage to {"input", "output", "total"};
    # raw OpenAI-style keys are still accepted.
    prompt = usage.get("input") or usage.get("prompt_tokens") or usage.get("promptTokens") or 0
    completion = usage.get("output") or usage.get("completion_tokens") or usage.get("completionTokens") or 0
    total = usage.get("total") or usage.get("total_tokens") or usage.get("totalTokens")
    if total is None:
        try:
            total = int(prompt) + int(completion)
        except (TypeError, ValueError):
            total = 0
    try:
        return int(total)
    except (TypeError, ValueError):
        return 0


def _filter_args(tool: str, args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    allowed = _ALLOWED_ARG_KEYS.get(tool, ())
    return {k: v for k, v in args.items() if k in allowed}


class AgentLoopExecutor(BaseNodeExecutor):
    component_ids = ("AgentLoop",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        runtime_config = context.runtime_config or {}
        max_iterations = _int_param(params, "maxIterations", 5, 1, 20)
        token_cap = _int_param(params, "tokenCap", 20000, 1, 1_000_000)
        timeout_s = _int_param(params, "timeoutS", 60, 1, 3600)
        allowlist_raw = params.get("allowlist") or runtime_config.get("xwsAllowlist") or []
        if isinstance(allowlist_raw, str):
            allowlist = [p.strip() for p in allowlist_raw.split(",") if p.strip()]
        elif isinstance(allowlist_raw, (list, tuple)):
            allowlist = [str(item) for item in allowlist_raw]
        else:
            allowlist = []

        if context.xws_client is None:
            raise RuntimeError(
                "AgentLoopExecutor requires an xws_client on the execution context"
            )

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
        system_prompt = str(params.get("systemPrompt", "")).strip() or AGENT_SYSTEM_PROMPT.replace(
            "{allowlist}", ", ".join(allowlist) or "(none)"
        )

        deadline = time.monotonic() + timeout_s
        messages: list[dict[str, Any]] = [{"role": "user", "content": str(input_payload.get("value", ""))}]
        transcript: list[dict[str, Any]] = []
        tokens_used = 0
        iterations_used = 0
        stop_reason = "final"

        for iteration in range(1, max_iterations + 1):
            if time.monotonic() > deadline:
                stop_reason = "timeout"
                break
            if tokens_used >= token_cap:
                stop_reason = "token_cap"
                break
            iterations_used = iteration

            prompt_text = json.dumps(messages, default=str)
            response = await context.llm_chat(prompt_text, system_prompt, model_hint, temperature)
            tokens_used += _usage_tokens(response.get("usage"))
            raw = str(response.get("content", ""))
            transcript.append({"iteration": iteration, "type": "llm", "content": raw})

            # Tolerate ```json fences / surrounding prose around the envelope.
            envelope, parse_error = parse_json_output(raw)
            if parse_error or not isinstance(envelope, dict):
                error = parse_error or "not an object"
                transcript.append({"iteration": iteration, "type": "error", "error": f"invalid envelope: {error}"})
                stop_reason = "invalid_envelope"
                break

            action = str(envelope.get("action", "")).lower()
            if action == "final":
                transcript.append({"iteration": iteration, "type": "final"})
                return NodeExecutionResult(
                    value=envelope.get("output", ""),
                    metadata={
                        "agentLoop": {
                            "iterations": iterations_used,
                            "stopReason": "final",
                            "tokensUsed": tokens_used,
                            "tokenCap": token_cap,
                            "transcript": transcript,
                        },
                        "provider": response.get("provider", "litellm"),
                        "model": response.get("model") or model_hint,
                        "usage": response.get("usage", {}),
                    },
                )
            if action != "tool":
                transcript.append({"iteration": iteration, "type": "error", "error": f"unknown action {action!r}"})
                stop_reason = "invalid_action"
                break

            tool = str(envelope.get("tool", ""))
            tool_class = str(envelope.get("toolClass", "")) or _TOOL_CLASS_BY_TOOL.get(tool, "")
            args = _filter_args(tool, envelope.get("args"))
            if tool_class not in allowlist:
                observation: dict[str, Any] = {
                    "error": f"toolClass {tool_class!r} is not in this node's allowlist"
                }
            elif tool not in _TOOL_CLASS_BY_TOOL:
                observation = {"error": f"unknown tool {tool!r}"}
            else:
                try:
                    observation = _dispatch_tool(
                        context.xws_client, tool, tool_class, context.run_id, args
                    )
                except Exception as exc:  # noqa: BLE001 — tool failure is an observation
                    observation = {"error": str(exc)}
            transcript.append({"iteration": iteration, "type": "tool", "tool": tool, "observation": observation})
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": json.dumps({"observation": observation}, default=str)})

        if stop_reason == "final":
            # Loop exhausted maxIterations without a final answer.
            stop_reason = "max_iterations"

        return NodeExecutionResult(
            value=json.dumps({"error": f"agent loop ended: {stop_reason}", "transcript": transcript}, default=str),
            metadata={
                "agentLoop": {
                    "iterations": iterations_used,
                    "stopReason": stop_reason,
                    "tokensUsed": tokens_used,
                    "tokenCap": token_cap,
                    "transcript": transcript,
                },
            },
        )


def _dispatch_tool(
    client: Any,
    tool: str,
    tool_class: str,
    run_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Map a loop tool call onto the XWS route surface (same as the executors)."""
    if tool == "XWSS3":
        operation = str(args.get("operation", "put")).lower()
        key = str(args.get("key", ""))
        bucket = str(args.get("bucket", "apigen-artifacts"))
        if not key:
            raise ValueError("XWSS3 requires a 'key' arg")
        if operation == "put":
            return client.request(
                method="PUT", path=f"/s3/{bucket}/{key}", tool_class=tool_class,
                run_id=run_id, json_body={"body": args.get("body")}, retry=True,
            )
        if operation == "get":
            return client.request(
                method="GET", path=f"/s3/{bucket}/{key}", tool_class=tool_class,
                run_id=run_id, retry=True,
            )
        raise ValueError(f"agent loop supports put/get only, got {operation!r}")
    if tool == "XWSLambdaInvoke":
        function_name = str(args.get("functionName", ""))
        bundle_hash = str(args.get("bundleHash", ""))
        if not (function_name and bundle_hash):
            raise ValueError("XWSLambdaInvoke requires 'functionName' and 'bundleHash' args")
        return client.request(
            method="POST", path=f"/lambda/invoke/{function_name}", tool_class=tool_class,
            run_id=run_id, json_body={"payload": args.get("payload"), "bundleHash": bundle_hash},
            idempotency_key=f"bundle-{bundle_hash}",
        )
    if tool == "XWSIAMEvaluate":
        principal = str(args.get("principal", ""))
        action = str(args.get("action", ""))
        resource = str(args.get("resource", ""))
        if not (principal and action and resource):
            raise ValueError("XWSIAMEvaluate requires 'principal', 'action', 'resource' args")
        return client.request(
            method="POST", path="/iam/evaluate", tool_class=tool_class,
            run_id=run_id,
            json_body={"principal": principal, "action": action, "resource": resource,
                       "context": args.get("context", {})},
        )
    if tool == "XWSRelayNotify":
        message = str(args.get("message", ""))
        return client.request(
            method="POST", path="/relay/notify", tool_class=tool_class,
            run_id=run_id,
            json_body={"message": message, "deepLink": str(args.get("deepLink", "")),
                       "channel": str(args.get("channel", "console")),
                       "card": args.get("card", {"title": message[:80]})},
        )
    raise ValueError(f"unknown tool {tool!r}")
