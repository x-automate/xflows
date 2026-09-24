"""Wave 4 tests: webhook receiver + time-trigger scheduler (XU-8)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from tests.test_auth import _FakeGateway, _make_app

from app.triggers import fire_due_triggers, trigger_slot_key


class WebhookReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.main = main_module
        self.gateway: _FakeGateway = main_module.temporal_gateway
        self._client_cm = TestClient(main_module.app)
        self.client = self._client_cm.__enter__()
        self.h = {"Authorization": "Bearer tok-owner"}

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)

    def _make_webhook_trigger(self) -> dict:
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self.h)
        created = self.client.post(
            "/projects/p1/triggers",
            json={
                "type": "webhook",
                "config": {"workflowId": "wf_hook", "input": "generated from webhook"},
            },
            headers=self.h,
        )
        assert created.status_code == 200, created.text
        return created.json()

    def test_webhook_trigger_gets_signature_secret(self) -> None:
        trigger = self._make_webhook_trigger()
        secret = trigger["config"].get("signatureSecret")
        self.assertTrue(secret)

    def test_missing_signature_rejected(self) -> None:
        trigger = self._make_webhook_trigger()
        response = self.client.post(f"/webhooks/{trigger['id']}", content=b"payload")
        self.assertEqual(response.status_code, 403)

    def test_bad_signature_rejected(self) -> None:
        trigger = self._make_webhook_trigger()
        response = self.client.post(
            f"/webhooks/{trigger['id']}",
            content=b"payload",
            headers={"X-Webhook-Signature": "sha256=deadbeef" * 8},
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_signature_creates_run_exactly_once(self) -> None:
        trigger = self._make_webhook_trigger()
        secret = trigger["config"]["signatureSecret"]
        self.client.post(
            "/workflows",
            json={"id": "wf_hook", "name": "Hook", "nodes": [], "edges": []},
            headers=self.h,
        )
        import hashlib
        import hmac

        signature = hmac.new(secret.encode(), b"payload", hashlib.sha256).hexdigest()
        first = self.client.post(
            f"/webhooks/{trigger['id']}",
            content=b"payload",
            headers={"X-Webhook-Signature": f"sha256={signature}", "X-Delivery-Id": "d1"},
        )
        self.assertEqual(first.status_code, 200)
        second = self.client.post(
            f"/webhooks/{trigger['id']}",
            content=b"payload",
            headers={"X-Webhook-Signature": f"sha256={signature}", "X-Delivery-Id": "d1"},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["runId"], second.json()["runId"])
        runs = self.client.get("/projects/p1/runs", headers=self.h).json()
        self.assertEqual(len(runs), 1)
        # The duplicate delivery must not start (or locally re-execute) the workflow again.
        self.assertEqual(len(self.gateway.started), 1)

    def test_unknown_webhook_404(self) -> None:
        self.assertEqual(self.client.post("/webhooks/trg_nope", content=b"x").status_code, 404)


class TimeTriggerSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.main = main_module
        self.gateway: _FakeGateway = main_module.temporal_gateway

    def _setup_store(self):
        import asyncio

        from app.models import TriggerCreateRequest, WorkflowCreateRequest, WorkflowNode
        from app.store import InMemoryStore

        async def build():
            store = InMemoryStore()
            await store.ensure_project("p1")
            await store.create_workflow(
                WorkflowCreateRequest(id="wf_sched", name="S", nodes=[
                    WorkflowNode(id="n1", componentId="Input")
                ], edges=[])
            )
            await store.create_trigger(
                "p1",
                TriggerCreateRequest(type="time", config={
                    "workflowId": "wf_sched",
                    "intervalSeconds": 60,
                    "input": "tick",
                }),
            )
            return store

        return asyncio.run(build())

    def test_slot_key_is_stable_within_interval(self) -> None:
        config = {"intervalSeconds": 60}
        t1 = datetime(2026, 9, 22, 12, 0, 30, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 22, 12, 1, 10, tzinfo=timezone.utc)
        key1 = trigger_slot_key("trg_1", config, t1)
        key2 = trigger_slot_key("trg_1", config, t2)
        self.assertNotEqual(key1, key2)  # crossed the 60s slot boundary
        self.assertEqual(key1, trigger_slot_key("trg_1", config, datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)))

    def test_fires_once_per_slot_under_duplicate_ticks(self) -> None:
        store = self._setup_store()
        created: list[str] = []

        async def create_run(workflow_id: str, key: str, input_value: str):
            run = await store.create_run(
                workflow_id, 1, input_value, trace_id=None, idempotency_key=key
            )
            created.append(run.id)
            return run

        now = datetime(2026, 9, 22, 12, 0, 30, tzinfo=timezone.utc)
        import asyncio

        fired1 = asyncio.run(fire_due_triggers(store, now=now, create_run=create_run))
        fired2 = asyncio.run(fire_due_triggers(store, now=now, create_run=create_run))
        self.assertEqual(len(fired1), 1)
        self.assertEqual(fired2, [])
        self.assertEqual(len(created), 1)

    def test_trigger_without_workflow_id_ignored(self) -> None:
        import asyncio

        from app.models import TriggerCreateRequest
        from app.store import InMemoryStore

        async def scenario():
            store = InMemoryStore()
            await store.ensure_project("p1")
            await store.create_trigger("p1", TriggerCreateRequest(type="time", config={}))
            calls: list[str] = []

            async def create_run(workflow_id, key, input_value):
                calls.append(workflow_id)
                return None

            fired = await fire_due_triggers(store, create_run=create_run)
            return fired, calls

        fired, calls = asyncio.run(scenario())
        self.assertEqual((fired, calls), ([], []))

    def test_disabled_triggers_are_skipped(self) -> None:
        import asyncio

        from app.models import TriggerCreateRequest
        from app.store import InMemoryStore

        async def scenario():
            store = InMemoryStore()
            await store.ensure_project("p1")
            await store.create_trigger("p1", TriggerCreateRequest(
                type="time", enabled=False,
                config={"workflowId": "wf_x", "intervalSeconds": 60},
            ))

            async def create_run(workflow_id, key, input_value):
                raise AssertionError("should not fire")

            return await fire_due_triggers(store, create_run=create_run)

        self.assertEqual(asyncio.run(scenario()), [])


if __name__ == "__main__":
    unittest.main()
