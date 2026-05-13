from __future__ import annotations

import unittest

from app.nodes import NodeGraphRunner, create_default_registry, normalize_workflow_graph
from app.nodes.context import NodeExecutionContext


class WorkerNodesEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_dispatches_chat_node(self) -> None:
        registry = create_default_registry()

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
            return {
                "content": f"answer:{prompt}",
                "provider": "test",
                "model": model_hint or "fake-model",
                "usage": {"tokens": 1},
            }

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

    async def test_runner_executes_normalized_graph(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "prompt", "componentId": "PromptTemplate", "params": {"template": "Q:{input}"}},
            {"id": "nested", "componentId": "Input", "parent": "container", "params": {}},
            {"id": "out", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "prompt", "kind": "data"},
            {"id": "e2", "source": "prompt", "target": "out", "kind": "data"},
            {"id": "e3", "source": "nested", "target": "out", "kind": "data"},
            {"id": "e4", "source": "in", "target": "out", "kind": "config"},
        ]
        normalized_nodes, normalized_edges = normalize_workflow_graph(nodes, edges)
        self.assertEqual([node["id"] for node in normalized_nodes], ["in", "prompt", "out"])
        self.assertEqual([edge["id"] for edge in normalized_edges], ["e1", "e2"])

        runner = NodeGraphRunner(nodes=normalized_nodes, edges=normalized_edges, user_input="hello")

        async def execute(node: dict, input_payload: dict) -> dict:
            component_id = node["componentId"]
            if component_id == "Input":
                return {"value": "hello"}
            if component_id == "PromptTemplate":
                return {"value": node["params"]["template"].replace("{input}", input_payload["value"])}
            return {"value": input_payload["value"]}

        outputs, order = await runner.run(execute)
        final_node_id = runner.resolve_output_node_id(order)
        self.assertEqual(outputs[final_node_id]["value"], "Q:hello")

    async def test_normalize_promotes_provider_child_to_container_node(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "llm", "componentId": "LLM", "params": {"temperature": 0.3}},
            {"id": "provider", "componentId": "LiteLLM", "parent": "llm", "params": {"model": "openai/gpt-4o-mini"}},
            {"id": "out", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "llm", "kind": "data"},
            {"id": "e2", "source": "llm", "target": "out", "kind": "data"},
        ]
        normalized_nodes, _ = normalize_workflow_graph(nodes, edges)
        llm_node = next(node for node in normalized_nodes if node["id"] == "llm")
        self.assertEqual(llm_node["componentId"], "LiteLLM")
        self.assertEqual(llm_node["params"]["model"], "openai/gpt-4o-mini")
        self.assertEqual(llm_node["providerComponentId"], "LiteLLM")

    async def test_registry_dispatches_litellm_node(self) -> None:
        registry = create_default_registry()

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
            return {
                "content": f"litellm:{model_hint}:{prompt}",
                "provider": "litellm",
                "model": model_hint,
                "usage": {"tokens": 2},
            }

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

        node = {"id": "n_litellm", "componentId": "LiteLLM", "params": {"model": "openai/gpt-4o-mini"}}
        result = await registry.dispatch(node=node, input_payload={"value": "ping"}, context=context)
        self.assertEqual(result["value"], "litellm:openai/gpt-4o-mini:ping")
        self.assertEqual(result["provider"], "litellm")

    async def test_api_caller_requires_url(self) -> None:
        registry = create_default_registry()

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
            return {
                "content": f"answer:{prompt}",
                "provider": "test",
                "model": model_hint or "fake-model",
                "usage": {"tokens": 1},
            }

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

        node = {"id": "n_api", "componentId": "ApiCaller", "params": {"method": "POST"}}
        with self.assertRaisesRegex(ValueError, "ApiCaller requires a URL"):
            await registry.dispatch(node=node, input_payload={"value": "ping"}, context=context)

    async def test_tracer_and_webhook_nodes_keep_payload(self) -> None:
        registry = create_default_registry()

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
            return {
                "content": f"answer:{prompt}",
                "provider": "test",
                "model": model_hint or "fake-model",
                "usage": {"tokens": 1},
            }

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

        webhook = {"id": "n_webhook", "componentId": "Webhook", "params": {"path": "/ingest", "method": "post"}}
        webhook_result = await registry.dispatch(node=webhook, input_payload={"value": "payload"}, context=context)
        self.assertEqual(webhook_result["value"], "payload")
        self.assertEqual(webhook_result["trigger"], "webhook")

        langfuse = {"id": "n_langfuse", "componentId": "LangfuseTracer", "params": {"host": "https://cloud.langfuse.com"}}
        langfuse_result = await registry.dispatch(node=langfuse, input_payload={"value": "payload"}, context=context)
        self.assertEqual(langfuse_result["value"], "payload")
        self.assertEqual(langfuse_result["traceProvider"], "langfuse")

        langsmith = {"id": "n_langsmith", "componentId": "LangsmithTracer", "params": {"project": "xflows"}}
        langsmith_result = await registry.dispatch(node=langsmith, input_payload={"value": "payload"}, context=context)
        self.assertEqual(langsmith_result["value"], "payload")
        self.assertEqual(langsmith_result["traceProvider"], "langsmith")


if __name__ == "__main__":
    unittest.main()
