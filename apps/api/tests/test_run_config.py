"""Run creation: project configs, secret refs and node policy reach the worker."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from tests.test_auth import _FakeGateway, _make_app

LLM_GRAPH = {
    "nodes": [
        {"id": "in", "componentId": "Input"},
        {"id": "llm", "componentId": "LLM", "retry": {"attempts": 5, "backoffMs": 10}, "timeoutS": 30,
         "onError": "continue"},
        {"id": "prov", "componentId": "LiteLLM", "parent": "llm", "params": {"model": "my-alias"}},
    ],
    "edges": [{"id": "e1", "source": "in", "target": "llm", "kind": "data"}],
}


class RunRuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.gateway: _FakeGateway = main_module.temporal_gateway
        self._client_cm = TestClient(main_module.app)
        self.client = self._client_cm.__enter__()
        self.h = {"Authorization": "Bearer tok-owner"}
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self.h)
        response = self.client.patch(
            "/projects/p1",
            json={"configs": {"litellmBaseUrl": "http://my-litellm:4000", "litellmApiKey": "sk-secret"}},
            headers=self.h,
        )
        assert response.status_code == 200, response.text

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)

    def _started_runtime_config(self) -> dict:
        # args = [workflow_def, input, run_id, trace_id, runtime_config, entryNodeId]
        return self.gateway.started[-1]["args"][-2]

    def test_project_run_without_inline_config_gets_project_config_and_secret_ref(self) -> None:
        response = self.client.post(
            "/projects/p1/runs",
            json={"input": "hi", "workflow": {"name": "F", **LLM_GRAPH}},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200, response.text)
        config = self._started_runtime_config()
        self.assertEqual(config["litellmBaseUrl"], "http://my-litellm:4000")
        self.assertEqual(config["litellmApiKeyRef"], "litellmApiKey")
        self.assertNotIn("litellmApiKey", config)

    def test_inline_config_overrides_project_and_secret_is_redacted_in_run_record(self) -> None:
        response = self.client.post(
            "/projects/p1/runs",
            json={
                "input": "hi",
                "workflow": {"name": "F", **LLM_GRAPH},
                "metadata": {"runtimeConfig": {"litellmBaseUrl": "http://other:4000", "litellmApiKey": "sk-inline"}},
            },
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200, response.text)
        config = self._started_runtime_config()
        self.assertEqual(config["litellmBaseUrl"], "http://other:4000")
        self.assertEqual(config["litellmApiKey"], "sk-inline")
        self.assertNotIn("litellmApiKeyRef", config)
        stored = self.client.get(f"/runs/{response.json()['id']}", headers=self.h).json()
        self.assertEqual(stored["metadata"]["runtimeConfig"]["litellmApiKey"], "***")
        self.assertNotIn("sk-inline", response.text)

    def test_workflow_run_inherits_project_from_workflow_metadata(self) -> None:
        self.client.post(
            "/workflows",
            json={"id": "wf_sched", "name": "S", **LLM_GRAPH, "metadata": {"projectId": "p1"}},
            headers=self.h,
        )
        response = self.client.post("/workflows/wf_sched/runs", json={"input": "tick"}, headers=self.h)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["projectId"], "p1")
        self.assertEqual(self._started_runtime_config()["litellmBaseUrl"], "http://my-litellm:4000")

    def test_node_execution_policy_survives_the_api(self) -> None:
        self.client.post(
            "/projects/p1/runs",
            json={"input": "hi", "workflow": {"name": "F", **LLM_GRAPH}},
            headers=self.h,
        )
        definition = self.gateway.started[-1]["args"][0]
        llm = next(node for node in definition["nodes"] if node["id"] == "llm")
        self.assertEqual(llm["retry"], {"attempts": 5, "backoffMs": 10})
        self.assertEqual(llm["timeoutS"], 30)
        self.assertEqual(llm["onError"], "continue")


if __name__ == "__main__":
    unittest.main()
