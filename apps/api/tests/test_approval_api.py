"""Wave 4 tests: HITL approval endpoints (docs 06 XU-5, 04 §5)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from tests.test_auth import _FakeGateway, _make_app


class ApprovalEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.main = main_module
        self.gateway: _FakeGateway = main_module.temporal_gateway
        self._client_cm = TestClient(main_module.app)
        self.client = self._client_cm.__enter__()
        self.owner = {"Authorization": "Bearer tok-owner"}
        self.reviewer = {"Authorization": "Bearer tok-rev"}
        self.operator = {"Authorization": "Bearer tok-op"}

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)

    def _run(self) -> str:
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self.owner)
        self.client.post(
            "/workflows",
            json={"id": "wf_gate", "name": "G", "nodes": [], "edges": []},
            headers=self.owner,
        )
        run = self.client.post(
            "/workflows/wf_gate/runs",
            json={"input": "x"},
            headers=self.operator,
        ).json()
        return run["id"]

    def _set_awaiting(self, run_id: str) -> None:
        run = self.main.store.runs[run_id]
        run.status = "awaiting_review"
        import asyncio

        asyncio.run(self.main.store.update_run(run))

    def test_roles_enforced_on_approval_endpoints(self) -> None:
        run_id = self._run()
        self._set_awaiting(run_id)
        denied = self.client.post(
            f"/runs/{run_id}/approve",
            json={"reviewer": "op"},
            headers=self.operator,
        )
        self.assertEqual(denied.status_code, 403)

    def _set_awaiting(self, run_id: str) -> None:
        run = self.main.store.runs[run_id]

        run.status = "awaiting_review"
        import asyncio

        asyncio.run(self.main.store.update_run(run))

    def test_not_awaiting_review_conflicts(self) -> None:
        run_id = self._run()
        response = self.client.post(
            f"/runs/{run_id}/approve",
            json={"reviewer": "alice"},
            headers=self.reviewer,
        )
        self.assertEqual(response.status_code, 409)

    def test_approve_forwards_temporal_signal(self) -> None:
        run_id = self._run()
        self._set_awaiting(run_id)
        response = self.client.post(
            f"/runs/{run_id}/approve",
            json={"reviewer": "alice", "comment": "ship it", "evidence": {"nodeId": "gate"}},
            headers=self.reviewer,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.gateway.signals, [(
            f"wf_gate:{run_id}",
            "approve",
            {
                "nodeId": "gate",
                "reviewer": "alice",
                "comment": "ship it",
                "evidence": {"nodeId": "gate"},
            },
        )])

    def test_reject_requires_comment(self) -> None:
        run_id = self._run()
        self._set_awaiting(run_id)
        missing = self.client.post(
            f"/runs/{run_id}/reject", json={"reviewer": "alice"}, headers=self.reviewer
        )
        self.assertEqual(missing.status_code, 422)
        ok = self.client.post(
            f"/runs/{run_id}/reject",
            json={"comment": "spec incomplete"},
            headers=self.reviewer,
        )
        self.assertEqual(ok.status_code, 200)
        signal = self.gateway.signals[-1]
        self.assertEqual(signal[1], "reject")
        self.assertEqual(signal[2]["reviewer"], "reviewer")  # caller name used
        self.assertEqual(signal[2]["comment"], "spec incomplete")

    def test_signal_received_event_updates_run_status(self) -> None:
        run_id = self._run()
        self._set_awaiting(run_id)
        import asyncio

        from app.models import InternalRunEventRequest

        asyncio.run(self.main.append_internal_event(
            run_id,
            InternalRunEventRequest(type="signal_received", nodeId="gate", payload={"signal": "rejected"}),
            x_internal_token="tok-worker",
        ))
        run = asyncio.run(self.main.store.get_run(run_id))
        self.assertEqual(run.status, "rejected")
        self.assertIsNotNone(run.finishedAt)

    def test_unknown_run_404(self) -> None:
        response = self.client.post(
            "/runs/run_nope/approve", json={"reviewer": "a"}, headers=self.reviewer
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
