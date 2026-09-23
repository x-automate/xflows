from __future__ import annotations

import asyncio
import unittest

from xflows_engine import NodeGraphRunner, normalize_workflow_graph
from xflows_engine.context import NodeExecutionContext
from xflows_engine.executors.flow import IfElseExecutor, LoudFailureExecutor, SwitchExecutor, WaitExecutor
from xflows_engine.predicates import evaluate_when, resolve_path


def _context() -> NodeExecutionContext:
    async def fake_llm_chat(prompt: str, system_prompt: str | None, model_hint: str | None, temperature: float) -> dict:
        return {"content": prompt, "provider": "test", "model": model_hint, "usage": {}}

    async def fake_http_request(method: str, url: str) -> str:
        return f"{method}:{url}"

    return NodeExecutionContext(
        run_id="run_1",
        trace_id="trace_1",
        user_input="hello",
        llm_chat=fake_llm_chat,
        http_request=fake_http_request,
        runtime_config={},
    )


class WhenPredicateTests(unittest.TestCase):
    def test_empty_or_missing_predicate_is_always_true(self) -> None:
        self.assertTrue(evaluate_when(None, {"value": "x"}))
        self.assertTrue(evaluate_when("", {"value": "x"}))
        self.assertTrue(evaluate_when("   ", {"value": "x"}))

    def test_equality_on_value(self) -> None:
        self.assertTrue(evaluate_when("value == 'approve'", {"value": "approve"}))
        self.assertFalse(evaluate_when("value == 'approve'", {"value": "reject"}))

    def test_numeric_equality_and_comparison(self) -> None:
        self.assertTrue(evaluate_when("count == 5", {"count": "5"}))
        self.assertTrue(evaluate_when("count > 3", {"count": 10}))
        self.assertFalse(evaluate_when("count >= 10", {"count": 9}))
        self.assertTrue(evaluate_when("score <= 1.5", {"score": 1.5}))

    def test_string_functions(self) -> None:
        self.assertTrue(evaluate_when("contains(value, 'error')", {"value": "an error occurred"}))
        self.assertFalse(evaluate_when("contains(value, 'fatal')", {"value": "all good"}))
        self.assertTrue(evaluate_when("startsWith(value, 'http')", {"value": "https://x"}))
        self.assertTrue(evaluate_when("endsWith(value, '.pdf')", {"value": "doc.pdf"}))

    def test_boolean_operators_and_parentheses(self) -> None:
        payload = {"value": "approved", "score": 9}
        self.assertTrue(evaluate_when("value == 'approved' && score > 5", payload))
        self.assertFalse(evaluate_when("value == 'approved' && score > 50", payload))
        self.assertTrue(evaluate_when("value == 'nope' || score > 5", payload))
        self.assertTrue(evaluate_when("!(value == 'nope')", payload))
        self.assertTrue(evaluate_when("(value == 'nope' || score > 5) && !(score < 1)", payload))

    def test_dotted_paths_and_missing_values(self) -> None:
        self.assertTrue(evaluate_when("meta.route == 'webhook'", {"value": "x", "meta": {"route": "webhook"}}))
        self.assertFalse(evaluate_when("meta.route == 'webhook'", {"value": "x"}))
        self.assertTrue(evaluate_when("meta.route != 'webhook'", {"value": "x"}))

    def test_invalid_syntax_raises(self) -> None:
        with self.assertRaisesRegex(Exception, "when expression"):
            evaluate_when("value === 'x'", {"value": "x"})
        with self.assertRaisesRegex(Exception, "when expression"):
            evaluate_when("value == )", {"value": "x"})

    def test_function_arity_enforced(self) -> None:
        with self.assertRaisesRegex(Exception, "takes exactly 2"):
            evaluate_when("contains(value)", {"value": "x"})

    def test_resolve_path(self) -> None:
        payload = {"value": {"a": {"b": 1}}}
        self.assertEqual(resolve_path(payload, "value.a.b"), 1)
        self.assertIsNone(resolve_path(payload, "value.missing"))


class ControlFlowGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_when_predicate_routes_conditionally(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "classify", "componentId": "Output", "params": {}},
            {"id": "reject", "componentId": "Output", "params": {}},
            {"id": "ok", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "classify", "kind": "data"},
            {"id": "e2", "source": "classify", "target": "reject", "kind": "data", "when": "value == 'abuse'"},
            {"id": "e3", "source": "classify", "target": "ok", "kind": "data", "when": "value != 'abuse'"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="abuse")

        async def execute(node: dict, input_payload: dict) -> dict:
            if node["id"] == "classify":
                return {"value": "abuse"}
            return {"value": f"{node['id']}:{input_payload.get('value', '')}"}

        outputs, _, statuses = await runner.run(execute)
        self.assertIn("reject", outputs)
        self.assertNotIn("ok", outputs)
        self.assertEqual(statuses["ok"], "skipped")
        self.assertEqual(outputs["reject"]["value"], "reject:abuse")

    async def test_error_edge_routes_failure_payload(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "bad", "componentId": "Output", "params": {}},
            {"id": "recover", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "bad", "kind": "data"},
            {"id": "e2", "source": "bad", "target": "recover", "kind": "error"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="x")

        async def execute(node: dict, input_payload: dict) -> dict:
            if node["id"] == "bad":
                raise RuntimeError("upstream exploded")
            if node["id"] == "recover":
                error_info = input_payload.get("error", {})
                return {"value": f"recovered from {error_info.get('componentId')}: {error_info.get('message')}"}
            return {"value": input_payload.get("value", "")}

        outputs, _, statuses = await runner.run(execute)
        self.assertEqual(outputs["recover"]["value"], "recovered from Output: upstream exploded")
        self.assertEqual(statuses["bad"], "failed_routed")

    async def test_node_without_error_edge_fails_run(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "bad", "componentId": "Output", "params": {}},
        ]
        edges = [{"id": "e1", "source": "in", "target": "bad", "kind": "data"}]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="x")

        async def execute(node: dict, input_payload: dict) -> dict:
            if node["id"] == "bad":
                raise RuntimeError("boom")
            return {"value": input_payload.get("value", "")}

        with self.assertRaisesRegex(RuntimeError, "boom"):
            await runner.run(execute)

    async def test_on_error_continue_passes_payload_downstream(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "flaky", "componentId": "Output", "params": {}, "onError": "continue"},
            {"id": "out", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "flaky", "kind": "data"},
            {"id": "e2", "source": "flaky", "target": "out", "kind": "data"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="keep")

        async def execute(node: dict, input_payload: dict) -> dict:
            if node["id"] == "flaky":
                raise RuntimeError("transient failure")
            return {"value": input_payload.get("value", "")}

        outputs, _, statuses = await runner.run(execute)
        self.assertEqual(outputs["out"]["value"], "keep")
        self.assertEqual(statuses["flaky"], "failed_continued")

    async def test_skipped_branch_does_not_deliver_downstream(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "gate", "componentId": "Output", "params": {}},
            {"id": "skipTarget", "componentId": "Output", "params": {}},
            {"id": "out", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "gate", "kind": "data"},
            {"id": "e2", "source": "gate", "target": "skipTarget", "kind": "data", "when": "value == 'never'"},
            {"id": "e3", "source": "skipTarget", "target": "out", "kind": "data"},
            {"id": "e4", "source": "in", "target": "out", "kind": "data"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="x")

        async def execute(node: dict, input_payload: dict) -> dict:
            return {"value": f"{node['id']}:{input_payload.get('value', '')}"}

        outputs, _, statuses = await runner.run(execute)
        self.assertEqual(statuses["skipTarget"], "skipped")
        self.assertEqual(outputs["out"]["value"], "out:in:x")

    async def test_parallel_nodes_in_same_level_run_concurrently(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "s1", "componentId": "Output", "params": {}},
            {"id": "s2", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "s1", "kind": "data"},
            {"id": "e2", "source": "in", "target": "s2", "kind": "data"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="x")
        started: list[str] = []
        overlapped = asyncio.Event()

        async def execute(node: dict, input_payload: dict) -> dict:
            if node["id"] == "in":
                return {"value": "seed"}
            started.append(node["id"])
            if node["id"] == "s1":
                await asyncio.sleep(0.05)
                overlapped.set()
                return {"value": "one"}
            await asyncio.wait_for(overlapped.wait(), timeout=1)
            return {"value": "two"}

        outputs, _, statuses = await runner.run(execute)
        self.assertEqual(outputs["s1"]["value"], "one")
        self.assertEqual(outputs["s2"]["value"], "two")
        self.assertEqual(started, ["s1", "s2"])

    async def test_batches_respect_dependencies(self) -> None:
        nodes = [
            {"id": "a", "componentId": "Input", "params": {}},
            {"id": "b", "componentId": "Output", "params": {}},
            {"id": "c", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "a", "target": "b", "kind": "data"},
            {"id": "e2", "source": "b", "target": "c", "kind": "data"},
        ]
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="x")
        self.assertEqual(runner.batches(), [["a"], ["b"], ["c"]])

    async def test_normalize_keeps_error_edges(self) -> None:
        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "llm", "componentId": "LLM", "params": {}},
            {"id": "out", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "llm", "kind": "data"},
            {"id": "e2", "source": "llm", "target": "out", "kind": "data"},
            {"id": "e3", "source": "llm", "target": "out", "kind": "error"},
            {"id": "e4", "source": "in", "target": "llm", "kind": "config"},
        ]
        _, normalized_edges = normalize_workflow_graph(nodes, edges)
        self.assertEqual({(e["source"], e["kind"]) for e in normalized_edges}, {("in", "data"), ("llm", "data"), ("llm", "error")})


class FlowExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_switch_matches_first_rule(self) -> None:
        executor = SwitchExecutor()
        node = {
            "id": "s",
            "componentId": "Switch",
            "params": {
                "routes": '[{"name":"urgent","contains":"asap"},{"name":"normal","contains":"hi"}]',
                "field": "value",
            },
        }
        result = await executor.execute(node, {"value": "please handle asap"}, _context())
        self.assertEqual(result.value, "please handle asap")
        self.assertEqual(result.metadata["switch"], {"route": "urgent", "matched": True})

    async def test_switch_no_match_leaves_route_empty(self) -> None:
        executor = SwitchExecutor()
        node = {"id": "s", "componentId": "Switch", "params": {"routes": '[{"name":"a","contains":"x"}]'}}
        result = await executor.execute(node, {"value": "nothing here"}, _context())
        self.assertEqual(result.metadata["switch"], {"route": "", "matched": False})

    async def test_switch_invalid_json_raises(self) -> None:
        executor = SwitchExecutor()
        node = {"id": "s", "componentId": "Switch", "params": {"routes": "{not json]"}}
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            await executor.execute(node, {"value": "x"}, _context())

    async def test_switch_supports_field_paths(self) -> None:
        executor = SwitchExecutor()
        node = {"id": "s", "componentId": "Switch", "params": {"routes": '[{"name":"yes","contains":"1"}]', "field": "meta.flag"}}
        result = await executor.execute(node, {"value": "x", "meta": {"flag": "r1"}}, _context())
        self.assertEqual(result.metadata["switch"], {"route": "yes", "matched": True})

    async def test_if_else_matched_and_fail_mode(self) -> None:
        executor = IfElseExecutor()
        node = {"id": "ie", "componentId": "IfElse", "params": {"contains": "ok", "mode": "warn"}}
        result = await executor.execute(node, {"value": "all ok"}, _context())
        self.assertEqual(result.metadata["ifelse"]["matched"], True)
        node_fail = {"id": "ie", "componentId": "IfElse", "params": {"contains": "ok", "mode": "fail"}}
        with self.assertRaisesRegex(ValueError, "does not contain"):
            await executor.execute(node_fail, {"value": "nope"}, _context())

    async def test_wait_sleeps_and_reports(self) -> None:
        executor = WaitExecutor()
        node = {"id": "w", "componentId": "Wait", "params": {"seconds": 0.05}}
        result = await executor.execute(node, {"value": "kept"}, _context())
        self.assertEqual(result.value, "kept")
        self.assertEqual(result.metadata["waitedSeconds"], 0.05)

    async def test_wait_rejects_non_numeric(self) -> None:
        executor = WaitExecutor()
        node = {"id": "w", "componentId": "Wait", "params": {"seconds": "soon"}}
        with self.assertRaisesRegex(ValueError, "numeric"):
            await executor.execute(node, {"value": "x"}, _context())

    async def test_loud_failure_executor_message(self) -> None:
        executor = LoudFailureExecutor()
        node = {"id": "x", "componentId": "Summarizer", "params": {}}
        with self.assertRaisesRegex(ValueError, "Summarizer"):
            await executor.execute(node, {"value": ""}, _context())


if __name__ == "__main__":
    unittest.main()
