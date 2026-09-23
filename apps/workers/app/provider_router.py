from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings

GATEWAY_ENDPOINT = "/v1/gateway/complete"
CHAT_COMPLETIONS_ENDPOINT = "/v1/chat/completions"


@dataclass
class ProviderRoute:
    model: str
    provider: str
    supports_tools: bool
    max_context_tokens: int


CAPABILITY_REGISTRY: dict[str, ProviderRoute] = {
    "openai/gpt-4o": ProviderRoute(
        model="openai/gpt-4o",
        provider="openai",
        supports_tools=True,
        max_context_tokens=128000,
    ),
    "openai/gpt-4o-mini": ProviderRoute(
        model="openai/gpt-4o-mini",
        provider="openai",
        supports_tools=True,
        max_context_tokens=128000,
    ),
    "ollama/llama3.1:8b": ProviderRoute(
        model="ollama/llama3.1:8b",
        provider="ollama",
        supports_tools=False,
        max_context_tokens=8192,
    ),
    "vllm/meta-llama/Llama-3.1-8B-Instruct": ProviderRoute(
        model="vllm/meta-llama/Llama-3.1-8B-Instruct",
        provider="vllm",
        supports_tools=True,
        max_context_tokens=8192,
    ),
}

DEFAULT_FALLBACK_CHAIN = [
    "openai/gpt-4o",
    "vllm/meta-llama/Llama-3.1-8B-Instruct",
    "ollama/llama3.1:8b",
]

PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
}


def _strip_xws_prefix(model: str) -> str:
    return str(model).removeprefix("xws/")


def _price_key(model: str) -> str:
    return _strip_xws_prefix(str(model)).split("/", 1)[-1].lower()


def estimate_cost(model: str, usage: dict[str, Any]) -> float | None:
    input_tokens = usage.get("input")
    output_tokens = usage.get("output")
    prices = PRICE_PER_1M_TOKENS.get(_price_key(model))
    if prices is None:
        return None
    try:
        input_value = float(input_tokens or 0)
        output_value = float(output_tokens or 0)
    except (TypeError, ValueError):
        return None
    input_price, output_price = prices
    return round(
        input_value / 1_000_000 * input_price + output_value / 1_000_000 * output_price,
        6,
    )


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
    cost = estimate_cost(model, normalized)
    if cost is not None:
        normalized["costUsd"] = cost
    return normalized


def _candidate_models(
    model_hint: str | None,
    runtime_config: dict[str, Any],
) -> list[str]:
    candidates: list[str] = []
    if model_hint:
        candidates.append(model_hint)
    runtime_model = runtime_config.get("litellmModel")
    if runtime_model:
        candidates.append(str(runtime_model))
    runtime_fallbacks = runtime_config.get("litellmFallbackModels")
    if isinstance(runtime_fallbacks, str):
        candidates.extend(part.strip() for part in runtime_fallbacks.split(",") if part.strip())
    elif isinstance(runtime_fallbacks, list):
        candidates.extend(str(model).strip() for model in runtime_fallbacks if str(model).strip())
    settings_fallbacks = getattr(settings, "litellm_fallback_models", "") or ""
    for part in str(settings_fallbacks).split(","):
        if part.strip():
            candidates.append(part.strip())
    seen: set[str] = set()
    unique: list[str] = []
    for model in candidates:
        if model and model not in seen:
            seen.add(model)
            unique.append(model)
    return unique


class LiteLLMRouter:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._client = httpx.AsyncClient(
            base_url=settings.litellm_base_url,
            timeout=60.0,
            transport=transport,
        )

    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model_hint: str | None = None,
        temperature: float = 0.2,
        runtime_config: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        runtime_config = runtime_config or {}
        gateway_base_url = runtime_config.get("xwsGatewayBaseUrl")
        is_gateway = bool(gateway_base_url)
        endpoint = GATEWAY_ENDPOINT if is_gateway else CHAT_COMPLETIONS_ENDPOINT
        base_url = (
            str(gateway_base_url)
            if is_gateway
            else str(runtime_config.get("litellmBaseUrl") or settings.litellm_base_url)
        )
        auth_key = (
            runtime_config.get("xwsGatewayApiKey")
            if is_gateway
            else runtime_config.get("litellmApiKey")
        ) or settings.litellm_api_key
        gateway_stage = runtime_config.get("gatewayStage") or runtime_config.get("xwsGatewayStage")

        candidate_models = _candidate_models(model_hint, runtime_config)
        if is_gateway:
            candidate_models = [_strip_xws_prefix(model) for model in candidate_models]
        last_error = "No providers available"

        for model in candidate_models:
            payload = self._build_payload(
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                response_format=response_format,
                tools=tools,
            )
            if is_gateway and gateway_stage:
                payload["stage"] = str(gateway_stage)
            try:
                response = await self._post(base_url, endpoint, payload, auth_key)
                if response.status_code >= 400:
                    body = response.text.strip()
                    last_error = (
                        f"status={response.status_code}, model={model}, "
                        f"body={body or response.reason_phrase}"
                    )
                    continue
                data = response.json()
                return {
                    "model": str(model),
                    "provider": self._provider_for(str(model), is_gateway),
                    "content": data["choices"][0]["message"]["content"],
                    "usage": _normalize_usage(data.get("usage", {}), str(model)),
                }
            except Exception as exc:
                last_error = str(exc)
                continue

        raise RuntimeError(f"LLM routing failed: {last_error}")

    async def _post(self, base_url: str, endpoint: str, payload: dict[str, Any], auth_key: str | None):
        headers: dict[str, str] = {}
        if auth_key:
            headers["Authorization"] = f"Bearer {auth_key}"
        if not base_url or base_url == settings.litellm_base_url:
            return await self._client.post(endpoint, json=payload, headers=headers)
        async with httpx.AsyncClient(base_url=base_url, timeout=60.0, transport=self._transport) as client:
            return await client.post(endpoint, json=payload, headers=headers)

    def _provider_for(self, model: str, is_gateway: bool) -> str:
        if is_gateway:
            return "xws-gateway"
        route = CAPABILITY_REGISTRY.get(
            model,
            ProviderRoute(model=model, provider="unknown", supports_tools=False, max_context_tokens=0),
        )
        return route.provider

    @staticmethod
    def _build_payload(
        model: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int | None,
        stop: list[str] | None,
        response_format: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": str(model),
            "messages": LiteLLMRouter._build_messages(prompt, system_prompt),
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
        return payload

    @staticmethod
    def _build_messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages
