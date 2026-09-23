"""Wave 4 tests: HITL approval node (docs 06 XU-5, 04 §5)."""

from __future__ import annotations

import unittest

from xflows_engine.context import NodeExecutionContext
from xflows_engine.executors.approval import ApprovalExecutor, normalize_decision


def _context(await_approval) -> NodeExecutionContext:
    async def fake_llm_chat(*args, **kwargs):
        return {"content": "", "provider": "test", "model": "m", "usage": {}}

    async def fake_http(method: str, url: str) -> str:
        return f"{method}:{url}"

    return NodeExecutionContext(
        run_id="run_1",
        trace_id="t1",
        user_input="hello",
        llm_chat=fake_llm_chat,
        http_request=fake_http,
        runtime_config={},
        await_approval=await_approval,
    )


def _node(**params) -> dict:
    return {"id": "gate", "componentId": "Approval", "params": params}


class NormalizeDecisionTests(unittest.TestCase):
    def test_aliases(self) -> None:
        self.assertEqual(normalize_decision("approve"), "approved")
        self.assertEqual(normalize_decision("APPROVED"), "approved")
        self.assertEqual(normalize_decision("reject"), "rejected")
        self.assertEqual(normalize_decision("request-changes"), "request_changes")
        self.assertEqual(normalize_decision("escalate"), "timeout")
        self.assertEqual(normalize_decision("gibberish"), "timeout")
        self.assertEqual(normalize_decision(None), "timeout")
        self.assertEqual(normalize_decision(42), "timeout")


class ApprovalExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_routes_decision_and_value(self) -> None:
        seen: list[dict] = []

        async def seam(request: dict) -> dict:
            seen.append(request)
            return {"decision": "approve", "reviewer": "alice", "comment": "ok"}

        result = await ApprovalExecutor().execute(
            _node(summary="Deploy spec v3", signalTimeoutS=60, notify={"relay": "#reviews"}),
            {"value": "preview"},
            _context(seam),
        )
        request = seen[0]
        self.assertEqual(request["runId"], "run_1")
        self.assertEqual(request["nodeId"], "gate")
        self.assertEqual(request["signalTimeoutS"], 60)
        self.assertEqual(request["notify"], {"relay": "#reviews"})
        self.assertEqual(result.value, {
            "decision": "approved", "reviewer": "alice", "comment": "ok", "evidence": {},
        })
        self.assertEqual(result.metadata["approval"]["decision"], "approved")
        self.assertEqual(result.metadata["approval"]["reviewer"], "alice")

    async def test_default_timeout_is_72h_and_clamped(self) -> None:
        seen: list[dict] = []

        async def seam(request: dict) -> dict:
            seen.append(request)
            return {"decision": "timeout"}

        await ApprovalExecutor().execute(_node(), {}, _context(seam))
        self.assertEqual(seen[0]["signalTimeoutS"], 259_200)

        await ApprovalExecutor().execute(_node(signalTimeoutS=999_999_999), {}, _context(seam))
        self.assertEqual(seen[1]["signalTimeoutS"], 2_592_000)

        await ApprovalExecutor().execute(_node(signalTimeoutS=0), {}, _context(seam))
        self.assertEqual(seen[2]["signalTimeoutS"], 1)

        await ApprovalExecutor().execute(_node(signalTimeoutS="bogus"), {}, _context(seam))
        self.assertEqual(seen[3]["signalTimeoutS"], 259_200)

    async def test_raw_string_decision_is_normalized(self) -> None:
        async def seam(request: dict) -> dict:
            return "reject"

        result = await ApprovalExecutor().execute(_node(), {}, _context(seam))
        self.assertEqual(result.value["decision"], "rejected")

    async def test_missing_seam_raises(self) -> None:
        async def fake_llm_chat(*args, **kwargs):
            return {}

        async def fake_http(method: str, url: str) -> str:
            return f"{method}:{url}"

        context = NodeExecutionContext(
            run_id="r", trace_id=None, user_input="u",
            llm_chat=fake_llm_chat, http_request=fake_http, runtime_config={},
        )
        with self.assertRaisesRegex(RuntimeError, "await_approval"):
            await ApprovalExecutor().execute(_node(), {}, context)

    async def test_summary_falls_back_to_input_value(self) -> None:
        seen: list[dict] = []

        async def seam(request: dict) -> dict:
            seen.append(request)
            return {"decision": "approved"}

        await ApprovalExecutor().execute(_node(), {"value": "spec hash abc"}, _context(seam))
        self.assertEqual(seen[0]["summary"], "spec hash abc")
        self.assertEqual(len(seen[0]["summary"]), len("spec hash abc"))

    async def test_long_summary_truncated_to_200(self) -> None:
        seen: list[dict] = []

        async def seam(request: dict) -> dict:
            seen.append(request)
            return {"decision": "approved"}

        await ApprovalExecutor().execute(_node(summary="x" * 500), {}, _context(seam))
        self.assertEqual(len(seen[0]["summary"]), 200)


class ApprovalGraphRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_decision_payload_drives_when_predicates(self) -> None:
        from xflows_engine import NodeGraphRunner

        nodes = [
            {"id": "in", "componentId": "Input", "params": {}},
            {"id": "gate", "componentId": "Approval", "params": {"summary": "deploy"}},
            {"id": "deploy", "componentId": "Output", "params": {}},
            {"id": "reject", "componentId": "Output", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "gate", "kind": "data"},
            {"id": "e2", "source": "gate", "target": "deploy", "kind": "data",
             "when": "value.decision == 'approved'"},
            {"id": "e3", "source": "gate", "target": "reject", "kind": "data",
             "when": "value.decision == 'rejected'"},
        ]

        async def seam(request: dict) -> dict:
            return {"decision": "approve", "reviewer": "alice"}

        context = _context(seam)
        registry = _registry()
        runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input="go")

        async def execute(node: dict, input_payload: dict) -> dict:
            return await registry.dispatch(node=node, input_payload=input_payload, context=context)

        outputs, _, statuses = await runner.run(execute)
        self.assertIn("deploy", outputs)
        self.assertNotIn("reject", outputs)
        self.assertEqual(statuses["reject"], "skipped")
        self.assertEqual(outputs["deploy"]["value"]["decision"], "approved")
        self.assertEqual(outputs["deploy"]["value"]["reviewer"], "alice")


def _registry():
    from xflows_engine import create_default_registry

    return create_default_registry()


if __name__ == "__main__":
    unittest.main()
