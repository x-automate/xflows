from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult
from ..schema_validation import build_repair_prompt, parse_json_output, parse_schema, validate_against_schema


def _int_param(params: dict[str, Any], key: str) -> int | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chat_options(params: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    max_tokens = _int_param(params, "max_tokens")
    if max_tokens:
        options["max_tokens"] = max_tokens
    stop = params.get("stop")
    if isinstance(stop, str) and stop.strip():
        options["stop"] = [part.strip() for part in stop.split(",") if part.strip()]
    elif isinstance(stop, list) and stop:
        options["stop"] = stop
    # LiteLLM provider nodes carry an explicit gateway endpoint (apiBase) and
    # optional apiKey. Forward them through the llm_chat seam so the worker's
    # router calls THAT LiteLLM API instead of the worker default (fix:
    # "LiteLLM provider must call a LiteLLM API, not a background ollama").
    api_base = params.get("apiBase")
    if isinstance(api_base, str) and api_base.strip():
        options["base_url"] = api_base.strip()
    api_key = params.get("apiKey")
    if isinstance(api_key, str) and api_key.strip():
        options["api_key"] = api_key.strip()
    return options


def _response_format(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": "output", "strict": True, "schema": schema},
    }


def _is_strict(params: dict[str, Any]) -> bool:
    return str(params.get("strictSchema", "true")).lower() != "false"


def _repair_attempts(params: dict[str, Any]) -> int:
    try:
        attempts = int(params.get("maxRepairAttempts", 1))
    except (TypeError, ValueError):
        attempts = 1
    return max(0, min(attempts, 5))


async def _chat_with_schema(
    context: NodeExecutionContext,
    params: dict[str, Any],
    prompt: str,
    system_prompt: str | None,
    model_hint: str | None,
    temperature: float,
) -> tuple[Any, dict[str, Any]]:
    options = _chat_options(params)
    schema_raw = params.get("outputSchema")
    schema = parse_schema(schema_raw) if schema_raw is not None and str(schema_raw).strip() != "" else None
    if schema is not None:
        options["response_format"] = _response_format(schema)
    first = await context.llm_chat(prompt, system_prompt, model_hint, temperature, **options)
    content = first.get("content", "")
    metadata = {
        "provider": first.get("provider", "litellm"),
        "model": first.get("model") or model_hint,
        "usage": first.get("usage", {}),
    }

    if schema is None:
        return content, metadata

    strict = _is_strict(params)
    max_repair = _repair_attempts(params)

    raw = str(content)
    parsed, parse_error = parse_json_output(raw)
    errors = [f"invalid JSON: {parse_error}"] if parse_error else validate_against_schema(parsed, schema)
    repair_attempts = 0
    while errors and repair_attempts < max_repair and strict:
        repair_attempts += 1
        repair_prompt = build_repair_prompt(prompt, schema, raw, errors)
        response = await context.llm_chat(repair_prompt, system_prompt, model_hint, temperature, **options)
        raw = str(response.get("content", ""))
        metadata["usage"] = response.get("usage", metadata["usage"])
        metadata["model"] = response.get("model") or metadata["model"]
        parsed, parse_error = parse_json_output(raw)
        errors = [f"invalid JSON: {parse_error}"] if parse_error else validate_against_schema(parsed, schema)

    metadata["repairAttempts"] = repair_attempts
    if not errors:
        metadata["schemaValidated"] = True
        return parsed, metadata
    if not strict:
        metadata["schemaValidated"] = False
        metadata["schemaErrors"] = errors[:5]
        return content, metadata
    raise ValueError(
        f"LLM output failed schema validation after {repair_attempts} repair attempt(s): {errors[0]}"
    )


class ChatLikeExecutor(BaseNodeExecutor):
    component_ids = ("LLM", "OpenAIChat", "AnthropicChat", "ReActAgent")

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
        prompt = str(input_payload.get("value", ""))
        system_prompt = (
            input_payload.get("system") if isinstance(input_payload.get("system"), str) else None
        )
        value, metadata = await _chat_with_schema(
            context, params, prompt, system_prompt, model_hint, temperature
        )
        return NodeExecutionResult(value=value, metadata=metadata)


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
        prompt = str(input_payload.get("value", ""))
        system_prompt = (
            input_payload.get("system") if isinstance(input_payload.get("system"), str) else None
        )
        value, metadata = await _chat_with_schema(
            context, params, prompt, system_prompt, model_hint, temperature
        )
        metadata["apiBase"] = params.get("apiBase") or runtime_config.get("litellmBaseUrl")
        return NodeExecutionResult(value=value, metadata=metadata)
