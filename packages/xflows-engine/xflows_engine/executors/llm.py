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
    return options


# Catalog defaults the web editor used to persist into every LiteLLM node as
# soon as any of its params was edited. A node still carrying one of these was
# never customised, so the project's configured LiteLLM endpoint/model
# (runtimeConfig.litellmBaseUrl / litellmModel) must win over it.
_LEGACY_LITELLM_DEFAULTS = {
    "apiBase": "http://litellm:4000",
    "model": "openai/gpt-4o-mini",
}


def _litellm_override(
    params: dict[str, Any],
    key: str,
    runtime_config: dict[str, Any],
    runtime_key: str,
) -> str | None:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value == _LEGACY_LITELLM_DEFAULTS.get(key) and runtime_config.get(runtime_key):
        return None
    return value


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
    extra_options: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    options = {**_chat_options(params), **(extra_options or {})}
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
        model_hint = _litellm_override(params, "model", runtime_config, "litellmModel") or (
            str(runtime_config.get("litellmModel"))
            if runtime_config.get("litellmModel") is not None
            else None
        )
        temperature = float(params.get("temperature", runtime_config.get("temperature", 0.2)))
        prompt = str(input_payload.get("value", ""))
        system_prompt = (
            input_payload.get("system") if isinstance(input_payload.get("system"), str) else None
        )
        # A LiteLLM provider node calls ITS LiteLLM API: the node's apiBase when
        # customised, else the project's litellmBaseUrl (resolved by the router).
        # Forwarded through the llm_chat seam as base_url/api_key overrides.
        extra_options: dict[str, Any] = {}
        api_base = _litellm_override(params, "apiBase", runtime_config, "litellmBaseUrl")
        if api_base:
            extra_options["base_url"] = api_base
        api_key = params.get("apiKey")
        if isinstance(api_key, str) and api_key.strip():
            extra_options["api_key"] = api_key.strip()
        value, metadata = await _chat_with_schema(
            context, params, prompt, system_prompt, model_hint, temperature, extra_options
        )
        metadata["apiBase"] = api_base or runtime_config.get("litellmBaseUrl")
        return NodeExecutionResult(value=value, metadata=metadata)
