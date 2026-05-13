from __future__ import annotations

import unittest

from app.nodes import NodeGraphRunner, create_default_registry, normalize_workflow_graph
from app.nodes.context import NodeExecutionContext


class ApiNodesEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_dispatches_chat_node(self) -> None:
        registry = create_default_registry()

        async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> str:
            return f"answer:{prompt}"

        async def fake_http_request(method: str, url: str) -> str:
            return f"{method}:{url}"

        context = NodeExecutionContext(
            run_id="run_1",
            trace_id="trace_1",
            user_input="hello",
            llm_chat=fake_llm_chat,
            http_request=fake_http_request,
        )
        node = {"id": "n2", "componentId": "OpenAIChat", "params": {"model": "m1"}}

        result = await registry.dispatch(node=node, input_payload={"value": "ping"}, context=context)
        self.assertEqual(result["value"], "answer:ping")

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


if __name__ == "__main__":
    unittest.main()
