"""Wave 4 tests: webhook receiver + time-trigger scheduler (XU-8)."""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timezone

from fastapi.testclient import TestClient
from tests.test_auth import _FakeGateway, _make_app

from app.triggers import fire_due_triggers, trigger_slot_key
from app.xws_sigv4 import (
    EMPTY_SHA256,
    build_canonical_request,
    build_string_to_sign,
    compute_signature,
)

_REGION = "local"
_SERVICE = "xws"


def _sign_event_request(
    *, method: str, path: str, access_key: str, secret_key: str, body: bytes, amz_date: str | None = None
) -> dict[str, str]:
    """Minimal test-local signer built from the ported verification primitives
    in ``app.xws_sigv4`` — orchestration only, no crypto duplicated."""
    now = datetime.now(UTC)
    amz_date = amz_date or now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
    headers = {"x-amz-date": amz_date, "x-amz-content-sha256": payload_hash}
    signed_headers = sorted(headers.keys())
    credential_scope = f"{date_stamp}/{_REGION}/{_SERVICE}/aws4_request"
    canonical_request = build_canonical_request(
        method=method, path=path, query_string="", headers=headers,
        signed_headers=signed_headers, payload_hash=payload_hash,
    )
    string_to_sign = build_string_to_sign(canonical_request, amz_date, credential_scope)
    signature = compute_signature(secret_key, date_stamp, _REGION, _SERVICE, string_to_sign)
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={';'.join(signed_headers)}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
    }


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

    def test_node_id_routes_entry_node_id_into_workflow_start(self) -> None:
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self.h)
        self.client.post(
            "/workflows",
            json={
                "id": "wf_hook_node",
                "name": "Hook",
                "nodes": [{"id": "n_hook", "componentId": "Webhook"}],
                "edges": [],
            },
            headers=self.h,
        )
        created = self.client.post(
            "/projects/p1/triggers",
            json={
                "type": "webhook",
                "config": {"workflowId": "wf_hook_node", "nodeId": "n_hook"},
            },
            headers=self.h,
        )
        self.assertEqual(created.status_code, 200, created.text)
        trigger = created.json()
        secret = trigger["config"]["signatureSecret"]

        import hashlib
        import hmac

        signature = hmac.new(secret.encode(), b"payload", hashlib.sha256).hexdigest()
        response = self.client.post(
            f"/webhooks/{trigger['id']}",
            content=b"payload",
            headers={"X-Webhook-Signature": f"sha256={signature}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.gateway.started), 1)
        self.assertEqual(self.gateway.started[0]["args"][-1], "n_hook")

    def test_trigger_creation_rejects_unknown_node_id(self) -> None:
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self.h)
        self.client.post(
            "/workflows",
            json={"id": "wf_hook_bad", "name": "Hook", "nodes": [], "edges": []},
            headers=self.h,
        )
        response = self.client.post(
            "/projects/p1/triggers",
            json={
                "type": "webhook",
                "config": {"workflowId": "wf_hook_bad", "nodeId": "does-not-exist"},
            },
            headers=self.h,
        )
        self.assertEqual(response.status_code, 400)


class EventReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.main = main_module
        self.gateway: _FakeGateway = main_module.temporal_gateway
        self._client_cm = TestClient(main_module.app)
        self.client = self._client_cm.__enter__()
        self.h = {"Authorization": "Bearer tok-owner"}

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)

    def _make_event_trigger(self) -> dict:
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self.h)
        self.client.post(
            "/workflows",
            json={"id": "wf_event", "name": "Event", "nodes": [], "edges": []},
            headers=self.h,
        )
        created = self.client.post(
            "/projects/p1/triggers",
            json={"type": "event", "config": {"workflowId": "wf_event"}},
            headers=self.h,
        )
        assert created.status_code == 200, created.text
        return created.json()

    def test_event_trigger_gets_key_pair(self) -> None:
        trigger = self._make_event_trigger()
        self.assertTrue(trigger["config"].get("accessKeyId", "").startswith("evt_"))
        self.assertTrue(trigger["config"].get("secretAccessKey"))

    def test_valid_signature_creates_run_exactly_once(self) -> None:
        trigger = self._make_event_trigger()
        access_key = trigger["config"]["accessKeyId"]
        secret_key = trigger["config"]["secretAccessKey"]
        body = b'{"functionName": "f1"}'
        headers = _sign_event_request(
            method="POST", path=f"/events/{trigger['id']}",
            access_key=access_key, secret_key=secret_key, body=body,
        )
        headers["X-Delivery-Id"] = "d1"

        first = self.client.post(f"/events/{trigger['id']}", content=body, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(f"/events/{trigger['id']}", content=body, headers=headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["runId"], second.json()["runId"])
        self.assertEqual(len(self.gateway.started), 1)

    def test_wrong_access_key_rejected(self) -> None:
        trigger = self._make_event_trigger()
        body = b"{}"
        headers = _sign_event_request(
            method="POST", path=f"/events/{trigger['id']}",
            access_key="evt_wrong", secret_key=trigger["config"]["secretAccessKey"], body=body,
        )
        response = self.client.post(f"/events/{trigger['id']}", content=body, headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_tampered_body_rejected(self) -> None:
        trigger = self._make_event_trigger()
        headers = _sign_event_request(
            method="POST", path=f"/events/{trigger['id']}",
            access_key=trigger["config"]["accessKeyId"],
            secret_key=trigger["config"]["secretAccessKey"], body=b"original",
        )
        response = self.client.post(f"/events/{trigger['id']}", content=b"tampered", headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_stale_timestamp_rejected(self) -> None:
        trigger = self._make_event_trigger()
        body = b"{}"
        stale_date = "20200101T000000Z"
        headers = _sign_event_request(
            method="POST", path=f"/events/{trigger['id']}",
            access_key=trigger["config"]["accessKeyId"],
            secret_key=trigger["config"]["secretAccessKey"], body=body, amz_date=stale_date,
        )
        response = self.client.post(f"/events/{trigger['id']}", content=body, headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_missing_authorization_rejected(self) -> None:
        trigger = self._make_event_trigger()
        response = self.client.post(f"/events/{trigger['id']}", content=b"{}")
        self.assertEqual(response.status_code, 403)

    def test_unknown_event_trigger_404(self) -> None:
        self.assertEqual(self.client.post("/events/trg_nope", content=b"{}").status_code, 404)


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
