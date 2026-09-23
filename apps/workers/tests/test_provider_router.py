from __future__ import annotations

import json
import unittest

import httpx

from app.provider_router import (
    CHAT_COMPLETIONS_ENDPOINT,
    GATEWAY_ENDPOINT,
    LiteLLMRouter,
    _candidate_models,
    _normalize_usage,
    estimate_cost,
)

CHAT_RESPONSE = {
    "choices": [{"message": {"content": "hello world"}}],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
}


def _capture_router(responses: list[tuple[int, dict]] | None = None):
    captured: list[dict] = []
    scripted = list(responses or [])

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "payload": json.loads(request.content.decode("utf-8")),
                "headers": dict(request.headers),
            }
        )
        if scripted:
            status, body = scripted.pop(0)
            return httpx.Response(status, json=body, request=request)
        return httpx.Response(200, json=CHAT_RESPONSE, request=request)

    return LiteLLMRouter(transport=httpx.MockTransport(handler)), captured


class RouterPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_includes_optional_fields(self) -> None:
        router, captured = _capture_router()
        response_format = {"type": "json_schema", "json_schema": {"name": "output", "schema": {}}}
        await router.chat(
            "classify this",
            system_prompt="be brief",
            model_hint="openai/gpt-4o-mini",
            temperature=0.7,
            max_tokens=512,
            stop=["END"],
            response_format=response_format,
            tools=[{"type": "function", "function": {"name": "noop"}}],
        )
        self.assertEqual(len(captured), 1)
        payload = captured[0]["payload"]
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["stop"], ["END"])
        self.assertEqual(payload["response_format"], response_format)
        self.assertEqual(payload["tools"], [{"type": "function", "function": {"name": "noop"}}])
        self.assertEqual(payload["temperature"], 0.7)
        self.assertEqual(payload["messages"][-1]["content"], "classify this")

    async def test_payload_omits_optional_fields_by_default(self) -> None:
        router, captured = _capture_router()
        await router.chat("hello")
        payload = captured[0]["payload"]
        for key in ("max_tokens", "stop", "response_format", "tools", "stage"):
            self.assertNotIn(key, payload)

    async def test_result_includes_normalized_usage_and_cost(self) -> None:
        router, _ = _capture_router()
        result = await router.chat("hello", model_hint="openai/gpt-4o-mini")
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["usage"]["input"], 1000)
        self.assertEqual(result["usage"]["output"], 500)
        self.assertEqual(result["usage"]["total"], 1500)
        self.assertAlmostEqual(result["usage"]["costUsd"], 1000 / 1e6 * 0.15 + 500 / 1e6 * 0.60)


class RouterFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_fallback_chain_is_used(self) -> None:
        router, captured = _capture_router(
            responses=[(500, {"error": "overloaded"})]
        )
        result = await router.chat(
            "hello",
            model_hint="openai/gpt-4o-mini",
            runtime_config={
                "litellmFallbackModels": ["vllm/meta-llama/Llama-3.1-8B-Instruct"],
            },
        )
        self.assertEqual(result["model"], "vllm/meta-llama/Llama-3.1-8B-Instruct")
        self.assertEqual([item["payload"]["model"] for item in captured], ["openai/gpt-4o-mini", "vllm/meta-llama/Llama-3.1-8B-Instruct"])

    async def test_all_candidates_failing_raises(self) -> None:
        router, _ = _capture_router(responses=[(500, {"error": "a"}) for _ in range(10)])
        with self.assertRaisesRegex(RuntimeError, "LLM routing failed"):
            await router.chat(
                "hello",
                model_hint="openai/gpt-4o-mini",
                runtime_config={"litellmFallbackModels": ["openai/gpt-4o"]},
            )


class GatewayRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_route_uses_gateway_endpoint_and_stage(self) -> None:
        router, captured = _capture_router()
        result = await router.chat(
            "classify",
            model_hint="xws/openai/gpt-4o-mini",
            runtime_config={
                "xwsGatewayBaseUrl": "http://xws-gateway:9000",
                "gatewayStage": "taskDetection",
                "xwsGatewayApiKey": "gw-key",
            },
        )
        self.assertEqual(captured[0]["path"], GATEWAY_ENDPOINT)
        payload = captured[0]["payload"]
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")
        self.assertEqual(payload["stage"], "taskDetection")
        self.assertEqual(result["provider"], "xws-gateway")
        self.assertEqual(captured[0]["headers"].get("authorization"), "Bearer gw-key")

    async def test_litellm_route_uses_chat_completions(self) -> None:
        router, captured = _capture_router()
        await router.chat("hello", runtime_config={"litellmBaseUrl": "http://litellm:4000"})
        self.assertEqual(captured[0]["path"], CHAT_COMPLETIONS_ENDPOINT)


class UsageHelperTests(unittest.TestCase):
    def test_normalize_usage_maps_keys(self) -> None:
        usage = _normalize_usage(
            {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            "ollama/llama3.1:8b",
        )
        self.assertEqual(usage, {"input": 10, "output": 4, "total": 14})

    def test_normalize_usage_computes_total_when_missing(self) -> None:
        usage = _normalize_usage({"prompt_tokens": 3, "completion_tokens": 2}, "openai/gpt-4o")
        self.assertEqual(usage["total"], 5)
        self.assertIn("costUsd", usage)

    def test_estimate_cost_unknown_model_is_none(self) -> None:
        self.assertIsNone(estimate_cost("some/custom-model", {"input": 100, "output": 100}))
        self.assertEqual(estimate_cost("xws/openai/gpt-4o", {"input": 1_000_000, "output": 1_000_000}), 12.5)


class CandidateModelTests(unittest.TestCase):
    def test_order_dedup_and_sources(self) -> None:
        candidates = _candidate_models(
            "openai/gpt-4o-mini",
            {"litellmModel": "openai/gpt-4o", "litellmFallbackModels": "openai/gpt-4o, ollama/llama3.1:8b"},
        )
        self.assertEqual(candidates, ["openai/gpt-4o-mini", "openai/gpt-4o", "ollama/llama3.1:8b", "vllm/meta-llama/Llama-3.1-8B-Instruct"])
        candidates = _candidate_models("hint", {"litellmFallbackModels": ["a", "b"]})
        self.assertEqual(candidates[0], "hint")
        self.assertEqual(candidates[1], "a")
        self.assertEqual(candidates[2], "b")

    def test_empty_hint_skipped(self) -> None:
        self.assertEqual(_candidate_models(None, {}), ["openai/gpt-4o", "vllm/meta-llama/Llama-3.1-8B-Instruct", "ollama/llama3.1:8b"])


if __name__ == "__main__":
    unittest.main()
