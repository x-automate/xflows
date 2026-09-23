"""Wave 4 tests: HITL approval gate + Temporal signal recording (docs 06 XU-5)."""

from __future__ import annotations

import asyncio
import unittest

from app.approval import ApprovalGate
from app.workflows import XFlowsWorkflow


class ApprovalGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_normalizes_signal_names(self) -> None:
        gate = ApprovalGate()
        decision = gate.record("gate", "approve", {"reviewer": "alice", "comment": "ok"})
        self.assertEqual(decision["decision"], "approved")
        self.assertEqual(decision["reviewer"], "alice")
        self.assertEqual(decision["comment"], "ok")
        self.assertEqual(decision["evidence"], {})

        self.assertEqual(gate.record("gate", "reject")["decision"], "rejected")
        self.assertEqual(gate.record("gate", "request_changes")["decision"], "request_changes")
        self.assertEqual(gate.record("gate", "timeout")["decision"], "timeout")

    async def test_record_rejects_evidence_of_wrong_type(self) -> None:
        gate = ApprovalGate()
        decision = gate.record("gate", "approve", {"evidence": "not-a-dict"})
        self.assertEqual(decision["evidence"], {})

    async def test_wait_resolves_with_recorded_decision(self) -> None:
        gate = ApprovalGate()
        gate.record("gate", "approve", {"reviewer": "bob"})
        decision = await gate.wait("gate", 1.0)
        self.assertEqual(decision["decision"], "approved")
        self.assertEqual(decision["reviewer"], "bob")

    async def test_wait_times_out_fail_closed(self) -> None:
        gate = ApprovalGate()
        decision = await gate.wait("gate", 0.02)
        self.assertEqual(decision, {"decision": "timeout", "reviewer": "", "comment": "", "evidence": {}})

    def test_has_get(self) -> None:
        gate = ApprovalGate()
        self.assertFalse(gate.has("gate"))
        self.assertIsNone(gate.get("gate"))
        gate.record("gate", "approved")
        self.assertTrue(gate.has("gate"))
        self.assertEqual(gate.get("gate")["decision"], "approved")


class WorkflowSignalTests(unittest.IsolatedAsyncioTestCase):
    def test_signal_handlers_record_gate_decisions(self) -> None:
        wf = XFlowsWorkflow()

        async def drive():
            await wf.approve({"nodeId": "gate", "reviewer": "carol"})
            await wf.reject({"nodeId": "gate2", "reviewer": "dave"})
            await wf.request_changes({"nodeId": "gate3"})
            await wf.approve(None)  # payload-less signal must not crash

        asyncio.run(drive())
        self.assertEqual(wf._approvals.get("gate")["decision"], "approved")
        self.assertEqual(wf._approvals.get("gate2")["decision"], "rejected")
        self.assertEqual(wf._approvals.get("gate3")["decision"], "request_changes")
        # A decision without nodeId cannot be routed and must not invent one.
        self.assertEqual(len(wf._approvals._decisions), 3)

    def test_workflow_defines_expected_signals(self) -> None:
        definition = getattr(XFlowsWorkflow, "__temporal_workflow_definition")
        signal_names = set(definition.signals)
        self.assertEqual(signal_names, {"approve", "reject", "request_changes"})


class _StubAsyncClient:
    """httpx.AsyncClient stand-in: routes by URL suffix to a factory response."""

    def __init__(self, routes: dict[str, object] | None = None) -> None:
        self._routes = routes or {}

    async def __aenter__(self) -> "_StubAsyncClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def get(self, url: str, **kwargs):
        from types import SimpleNamespace

        for suffix, factory in self._routes.items():
            if url.endswith(suffix):
                return factory()
        return SimpleNamespace(status_code=404, json=lambda: {})


class SecretRefResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import app.activities as activities

        self.activities = activities
        self._original_cache = dict(activities._SECRET_CACHE)
        activities._SECRET_CACHE.clear()

    def tearDown(self) -> None:
        self.activities._SECRET_CACHE.clear()
        self.activities._SECRET_CACHE.update(self._original_cache)

    def test_refs_resolved_via_internal_endpoint_and_cached(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        def make_stub(**kwargs):
            return _StubAsyncClient({
                "litellm-key": lambda: SimpleNamespace(
                    status_code=200, json=lambda: {"value": "sk-123"}
                ),
            })

        with mock.patch.object(self.activities.httpx, "AsyncClient", make_stub):
            resolved = asyncio.run(self.activities._resolve_secret_refs(
                {"litellmApiKeyRef": "litellm-key", "litellmModel": "m"}, "run_1"
            ))
        self.assertEqual(resolved["litellmApiKey"], "sk-123")
        self.assertNotIn("litellmApiKeyRef", resolved)
        self.assertEqual(resolved["litellmModel"], "m")
        # Cached per (run_id, name): a second resolution must not refetch.
        self.assertIn(("run_1", "litellm-key"), self.activities._SECRET_CACHE)
        self.assertEqual(self.activities._SECRET_CACHE[("run_1", "litellm-key")], "sk-123")

    def test_missing_secret_leaves_ref_in_place(self) -> None:
        from unittest import mock

        with mock.patch.object(
            self.activities.httpx, "AsyncClient",
            lambda **kwargs: _StubAsyncClient({}),
        ):
            resolved = asyncio.run(self.activities._resolve_secret_refs(
                {"litellmApiKeyRef": "unknown"}, "run_2"
            ))
        self.assertEqual(resolved, {"litellmApiKeyRef": "unknown"})


class ApprovalActivityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import app.activities as activities

        self.activities = activities
        self._original_publish = activities.publish_event
        self._original_client = activities._build_xws_client

    def tearDown(self) -> None:
        self.activities.publish_event = self._original_publish
        self.activities._build_xws_client = self._original_client

    async def test_prepare_approval_records_awaiting_review(self) -> None:
        recorded: list[tuple[str, str | None, dict]] = []

        async def publish_stub(run_id, event_type, *, node_id=None, payload=None, trace_id=None, event_key=None):
            recorded.append((event_type, node_id, payload))

        self.activities.publish_event = publish_stub
        self.activities._build_xws_client = lambda run_id: None
        request = await self.activities.prepare_approval(
            {"id": "gate", "componentId": "Approval",
             "params": {"summary": "deploy v1", "signalTimeoutS": 60}},
            {"value": "preview"},
            "run_9",
            "trace_9",
        )
        self.assertEqual(request["signalTimeoutS"], 60)
        self.assertEqual(request["nodeId"], "gate")
        self.assertEqual(recorded, [
            ("run_awaiting_review", "gate", {"summary": "deploy v1", "signalTimeoutS": 60}),
        ])

    async def test_record_approval_publishes_signal_received(self) -> None:
        recorded: list[tuple[str, dict]] = []

        async def publish_stub(run_id, event_type, *, node_id=None, payload=None, trace_id=None, event_key=None):
            recorded.append((event_type, payload))

        self.activities.publish_event = publish_stub
        await self.activities.record_approval(
            "run_9", "trace_9", "gate",
            {"decision": "approved", "reviewer": "alice", "comment": "ok", "evidence": {}},
        )
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0][0], "signal_received")
        self.assertEqual(recorded[0][1]["signal"], "approved")
        self.assertEqual(recorded[0][1]["reviewer"], "alice")


if __name__ == "__main__":
    unittest.main()
