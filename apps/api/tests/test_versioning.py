"""Wave 4 tests: versioning, publish/archive/DELETE, durable 503 (XU-9, XF-03/05)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from tests.test_auth import _FakeGateway, _make_app

NODES = [{"id": "n1", "componentId": "Input", "params": {}}]
EDGES: list[dict] = []


class VersioningTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.main = main_module
        self.gateway: _FakeGateway = main_module.temporal_gateway
        self._client_cm = TestClient(main_module.app)
        self.client = self._client_cm.__enter__()
        self.h = {"Authorization": "Bearer tok-owner"}

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)

    def _create_project_run(self, name: str = "W", extra_node: bool = False) -> None:
        nodes = list(NODES)
        if extra_node:
            nodes = nodes + [{"id": "n2", "componentId": "Output", "params": {}}]
        response = self.client.post(
            "/projects/p1/runs",
            json={"input": "hello", "workflow": {"name": name, "nodes": nodes, "edges": EDGES}},
            headers=self.h,
        )
        assert response.status_code in (200, 503), response.text

    def _versions(self) -> dict[str, int]:
        return {wf["id"]: wf["version"] for wf in self.client.get("/workflows", headers=self.h).json()}

    def test_upsert_bumps_version_only_on_definition_change(self) -> None:
        self._create_project_run()
        self.assertEqual(self._versions()["wf_p1"], 1)
        # Identical re-save: no bump.
        self._create_project_run()
        self.assertEqual(self._versions()["wf_p1"], 1)
        # Changed definition: bump.
        self._create_project_run(name="renamed", extra_node=True)
        self.assertEqual(self._versions()["wf_p1"], 2)

    def test_publish_archive_and_archived_rejects_runs(self) -> None:
        self._create_project_run()
        self.assertEqual(
            self.client.post("/workflows/wf_p1/publish", headers=self.h).json()["status"], "published"
        )
        self.assertEqual(
            self.client.post("/workflows/wf_p1/archive", headers=self.h).json()["status"], "archived"
        )
        blocked = self.client.post(
            "/projects/p1/runs",
            json={"input": "x", "workflow": {"name": "W", "nodes": NODES, "edges": EDGES}},
            headers=self.h,
        )
        self.assertEqual(blocked.status_code, 409)

    def test_delete_workflow_with_runs_conflicts_without_runs_deletes(self) -> None:
        self._create_project_run()
        response = self.client.delete("/workflows/wf_p1", headers=self.h)
        self.assertEqual(response.status_code, 409)
        # Fresh workflow with no runs: deletable.
        created = self.client.post(
            "/workflows",
            json={"id": "wf_empty", "name": "E", "nodes": NODES, "edges": EDGES},
            headers=self.h,
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.client.delete("/workflows/wf_empty", headers=self.h).status_code, 200)
        self.assertNotIn("wf_empty", self._versions())

    def test_delete_project(self) -> None:
        response = self.client.post("/projects", json={"id": "p2", "name": "P2"}, headers=self.h)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.delete("/projects/p2", headers=self.h).status_code, 200)
        self.assertEqual(self.client.get("/projects/p2", headers=self.h).status_code, 404)

    def test_durable_workflow_503_when_temporal_down(self) -> None:
        self.gateway.connected_flag = False
        try:
            created = self.client.post(
                "/workflows",
                json={"id": "wf_durable", "name": "D", "nodes": NODES, "edges": EDGES, "durable": True},
                headers=self.h,
            )
            self.assertEqual(created.status_code, 200)
            response = self.client.post(
                "/workflows/wf_durable/runs",
                json={"input": "go"},
                headers=self.h,
            )
            self.assertEqual(response.status_code, 503)
        finally:
            self.gateway.connected_flag = True

    def test_durable_workflow_runs_when_temporal_connected(self) -> None:
        created = self.client.post(
            "/workflows",
            json={"id": "wf_durable2", "name": "D2", "nodes": NODES, "edges": EDGES, "durable": True},
            headers=self.h,
        )
        self.assertEqual(created.status_code, 200)
        response = self.client.post(
            "/workflows/wf_durable2/runs",
            json={"input": "go"},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.gateway.started), 1)

    def test_non_durable_fallback_still_allowed(self) -> None:
        self.gateway.connected_flag = False
        try:
            response = self.client.post(
                "/projects/p1/runs",
                json={"input": "x", "workflow": {"name": "W", "nodes": NODES, "edges": EDGES}},
                headers=self.h,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.gateway.started, [])
        finally:
            self.gateway.connected_flag = True


if __name__ == "__main__":
    unittest.main()
