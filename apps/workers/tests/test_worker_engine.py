from __future__ import annotations

import unittest

from xflows_engine import create_default_registry
from xflows_engine.context import NodeExecutionContext


class WorkerEngineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_engine_importable_and_dispatchable(self) -> None:
        registry = create_default_registry()

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
            return {"content": f"answer:{prompt}", "provider": "test", "model": model_hint or "fake-model", "usage": {"tokens": 1}}

        async def fake_http_request(method: str, url: str) -> str:
            return f"{method}:{url}"

        context = NodeExecutionContext(
            run_id="run_1",
            trace_id="trace_1",
            user_input="hello",
            llm_chat=fake_llm_chat,
            http_request=fake_http_request,
            runtime_config={},
        )
        node = {"id": "n2", "componentId": "LLM", "params": {"model": "m1"}}
        result = await registry.dispatch(node=node, input_payload={"value": "ping"}, context=context)
        self.assertEqual(result["value"], "answer:ping")
        self.assertEqual(result["provider"], "test")
        self.assertEqual(result["usage"], {"tokens": 1})


if __name__ == "__main__":
    unittest.main()
