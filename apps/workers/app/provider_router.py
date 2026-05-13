from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings


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


class LiteLLMRouter:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=settings.litellm_base_url, timeout=60.0)

    async def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model_hint: str | None = None,
        temperature: float = 0.2,
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_config = runtime_config or {}
        candidate_models = [model_hint] if model_hint else []
        runtime_model = runtime_config.get("litellmModel")
        if runtime_model and runtime_model not in candidate_models:
            candidate_models.append(runtime_model)
        candidate_models.extend([model for model in DEFAULT_FALLBACK_CHAIN if model != model_hint])
        last_error = "No providers available"
        auth_key = runtime_config.get("litellmApiKey") or settings.litellm_api_key
        base_url = str(runtime_config.get("litellmBaseUrl") or settings.litellm_base_url)

        for model in candidate_models:
            if not model:
                continue
            try:
                payload = {
                    "model": str(model),
                    "messages": self._build_messages(prompt, system_prompt),
                    "temperature": temperature,
                }
                headers = {}
                if auth_key:
                    headers["Authorization"] = f"Bearer {auth_key}"
                if base_url == settings.litellm_base_url:
                    response = await self._client.post(
                        "/v1/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                else:
                    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
                        response = await client.post(
                            "/v1/chat/completions",
                            json=payload,
                            headers=headers,
                        )
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
                    "provider": CAPABILITY_REGISTRY.get(
                        str(model),
                        ProviderRoute(model=str(model), provider="unknown", supports_tools=False, max_context_tokens=0),
                    ).provider,
                    "content": data["choices"][0]["message"]["content"],
                    "usage": data.get("usage", {}),
                }
            except Exception as exc:
                last_error = str(exc)
                continue

        raise RuntimeError(f"LiteLLM routing failed: {last_error}")

    @staticmethod
    def _build_messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages
