from __future__ import annotations

import unittest

from xflows_engine import NodeGraphRunner, create_default_registry, normalize_workflow_graph
from xflows_engine.context import NodeExecutionContext


def _fake_llm_chat(model_hint: str | None = None, provider: str = "test"):
    async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
        return {
            "content": f"answer:{prompt}",
            "provider": provider,
            "model": model_hint or "fake-model",
            "usage": {"tokens": 1},
        }

    return fake_llm_chat


async def fake_http_request(method: str, url: str) -> str:
    return f"{method}:{url}"


def _context() -> NodeExecutionContext:
    return NodeExecutionContext(
        run_id="run_1",
        trace_id="trace_1",
        user_input="hello",
        llm_chat=_fake_llm_chat(),
        http_request=fake_http_request,
        runtime_config={},
    )


class EngineRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_dispatches_chat_node(self) -> None:
        registry = create_default_registry()
        node = {"id": "n2", "componentId": "LLM", "params": {"model": "m1"}}

        result = await registry.dispatch(node=node, input_payload={"value": "ping"}, context=_context())
        self.assertEqual(result["value"], "answer:ping")
        self.assertEqual(result["provider"], "test")
        self.assertEqual(result["model"], "m1")
        self.assertEqual(result["usage"], {"tokens": 1})

    async def test_registry_dispatches_litellm_node(self) -> None:
        registry = create_default_registry()
        context = NodeExecutionContext(
            run_id="run_1",
            trace_id="trace_1",
            user_input="hello",
            llm_chat=_fake_llm_chat(model_hint="openai/gpt-4o-mini", provider="litellm"),
            http_request=fake_http_request,
            runtime_config={},
        )
        node = {"id": "n_litellm", "componentId": "LiteLLM", "params": {"model": "openai/gpt-4o-mini"}}

        result = await registry.dispatch(node=node, input_payload={"value": "ping"}, context=context)
        self.assertEqual(result["value"], "answer:ping")
        self.assertEqual(result["provider"], "litellm")
        self.assertEqual(result["model"], "openai/gpt-4o-mini")

    async def test_chat_node_uses_system_prompt_from_upstream_metadata(self) -> None:
        registry = create_default_registry()
        calls: list[str] = []

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
            calls.append(system_prompt or "")
            return {"content": "ok", "provider": "test", "model": model_hint, "usage": {}}

        context = NodeExecutionContext(
            run_id="run_1",
            trace_id="trace_1",
            user_input="hello",
            llm_chat=fake_llm_chat,
            http_request=fake_http_request,
            runtime_config={},
        )
        node = {"id": "n2", "componentId": "LLM", "params": {}}
        result = await registry.dispatch(node=node, input_payload={"value": "ping", "system": "be brief"}, context=context)
        self.assertEqual(result["value"], "ok")
        self.assertEqual(calls, ["be brief"])

    async def test_prompt_template_renders_and_carries_system(self) -> None:
        registry = create_default_registry()
        node = {"id": "p1", "componentId": "PromptTemplate", "params": {"template": "Q:{input}", "system": "custom"}}

        result = await registry.dispatch(node=node, input_payload={"value": "ping"}, context=_context())
        self.assertEqual(result["value"], "Q:ping")
        self.assertEqual(result["system"], "custom")

    async def test_input_output_passthrough(self) -> None:
        registry = create_default_registry()
        node = {"id": "i1", "componentId": "Input", "params": {}}
        result = await registry.dispatch(node=node, input_payload={"value": "x"}, context=_context())
        self.assertEqual(result["value"], "hello")
        output_node = {"id": "o1", "componentId": "Output", "params": {}}
        result = await registry.dispatch(node=output_node, input_payload={"value": "done"}, context=_context())
        self.assertEqual(result["value"], "done")

    async def test_unknown_component_fails_loudly_in_registry(self) -> None:
        registry = create_default_registry()
        node = {"id": "u1", "componentId": "DoesNotExist", "params": {}}
        with self.assertRaisesRegex(ValueError, "no registered executor"):
            await registry.dispatch(node=node, input_payload={"value": "kept"}, context=_context())

    async def test_http_request_and_api_caller(self) -> None:
        registry = create_default_registry()
        http_node = {"id": "h1", "componentId": "HttpRequest", "params": {"method": "GET", "url": "https://x/y"}}
        result = await registry.dispatch(node=http_node, input_payload={"value": ""}, context=_context())
        self.assertEqual(result["value"], "GET:https://x/y")
        api_node = {"id": "a1", "componentId": "ApiCaller", "params": {"method": "POST", "url": "https://x/y"}}
        result = await registry.dispatch(node=api_node, input_payload={"value": ""}, context=_context())
        self.assertEqual(result["value"], "POST:https://x/y")

    async def test_http_request_requires_url(self) -> None:
        registry = create_default_registry()
        node = {"id": "h1", "componentId": "HttpRequest", "params": {"method": "GET"}}
        with self.assertRaisesRegex(ValueError, "HttpRequest requires a URL"):
            await registry.dispatch(node=node, input_payload={"value": ""}, context=_context())

    async def test_api_caller_requires_url(self) -> None:
        registry = create_default_registry()
        node = {"id": "n_api", "componentId": "ApiCaller", "params": {"method": "POST"}}
        with self.assertRaisesRegex(ValueError, "ApiCaller requires a URL"):
            await registry.dispatch(node=node, input_payload={"value": "ping"}, context=_context())

    async def test_tracer_and_webhook_nodes_keep_payload(self) -> None:
        registry = create_default_registry()
        webhook = {"id": "n_webhook", "componentId": "Webhook", "params": {"path": "/ingest", "method": "post"}}
        webhook_result = await registry.dispatch(node=webhook, input_payload={"value": "payload"}, context=_context())
        self.assertEqual(webhook_result["value"], "payload")
        self.assertEqual(webhook_result["trigger"], "webhook")

        langfuse = {"id": "n_langfuse", "componentId": "LangfuseTracer", "params": {"host": "https://cloud.langfuse.com"}}
        langfuse_result = await registry.dispatch(node=langfuse, input_payload={"value": "payload"}, context=_context())
        self.assertEqual(langfuse_result["value"], "payload")
        self.assertEqual(langfuse_result["traceProvider"], "langfuse")

        langsmith = {"id": "n_langsmith", "componentId": "LangsmithTracer", "params": {"project": "xflows"}}
        langsmith_result = await registry.dispatch(node=langsmith, input_payload={"value": "payload"}, context=_context())
        self.assertEqual(langsmith_result["value"], "payload")
        self.assertEqual(langsmith_result["traceProvider"], "langsmith")


class EngineGraphTests(unittest.IsolatedAsyncioTestCase):
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

        outputs, order, statuses = await runner.run(execute)
        final_node_id = runner.resolve_output_node_id(order)
        self.assertEqual(outputs[final_node_id]["value"], "Q:hello")
        self.assertEqual(statuses[final_node_id], "succeeded")

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

    async def test_fan_in_merges_branches_deterministically(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "a", "componentId": "Output", "params": {}},
            {"id": "b", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "a", "kind": "data"},
            {"id": "e2", "source": "in", "target": "b", "kind": "data"},
            {"id": "e3", "source": "b", "target": "a", "kind": "data"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="seed")
        seen: dict[str, dict] = {}

        async def execute(node: dict, input_payload: dict) -> dict:
            seen[node["id"]] = input_payload
            return {"value": f"{node['id']}:{input_payload.get('value', '')}"}

        outputs, _, statuses = await runner.run(execute)
        self.assertEqual(outputs["a"]["value"], "a:in:seed")
        self.assertEqual(seen["a"]["value"], "in:seed")
        self.assertEqual(set(seen["a"]["branches"]), {"e1", "e3"})
        self.assertEqual(seen["a"]["branches"]["e1"]["value"], "in:seed")
        self.assertEqual(seen["a"]["branches"]["e3"]["value"], "b:in:seed")
        self.assertEqual(statuses["a"], "succeeded")

    async def test_unknown_component_fails_loudly(self) -> None:
        registry = create_default_registry()
        node = {"id": "u1", "componentId": "DoesNotExist", "params": {}}
        with self.assertRaisesRegex(ValueError, "no registered executor"):
            await registry.dispatch(node=node, input_payload={"value": "kept"}, context=_context())

    async def test_topo_sort_rejects_cycles(self) -> None:
        nodes = [
            {"id": "a", "componentId": "Input", "params": {}},
            {"id": "b", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "a", "target": "b", "kind": "data"},
            {"id": "e2", "source": "b", "target": "a", "kind": "data"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="x")
        with self.assertRaisesRegex(ValueError, "cycle"):
            runner.ordered_node_ids()


if __name__ == "__main__":
    unittest.main()
