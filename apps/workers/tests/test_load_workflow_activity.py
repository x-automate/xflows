"""Wave 5 tests: xflows.load_workflow activity (docs 06 XU-3)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from app import activities

DEFINITION = {"name": "helper", "nodes": [{"id": "in"}], "edges": []}


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class LoadWorkflowActivityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.client_timeout: Any = None

    def install(self, status_code: int, payload: Any, *, token: str | None = "tok") -> None:
        response = FakeResponse(status_code, payload)
        requests = self.requests
        holder = self

        class FakeAsyncClient:
            def __init__(self, timeout: Any = None, **kwargs: Any) -> None:
                holder.client_timeout = timeout

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(self, *exc: Any) -> bool:
                return False

            async def get(self, url: str, headers: dict | None = None) -> FakeResponse:
                requests.append({"url": url, "headers": headers})
                return response

        client_patcher = mock.patch.object(activities.httpx, "AsyncClient", FakeAsyncClient)
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        token_patcher = mock.patch.object(activities.settings, "internal_api_token", token)
        token_patcher.start()
        self.addCleanup(token_patcher.stop)
        base_patcher = mock.patch.object(activities.settings, "api_base_url", "http://api:8000")
        base_patcher.start()
        self.addCleanup(base_patcher.stop)

    async def test_fetches_definition_from_wrapper_payload(self) -> None:
        self.install(200, {"definition": dict(DEFINITION)})

        result = await activities.load_workflow("wf1")

        self.assertEqual(result, DEFINITION)
        self.assertEqual(self.client_timeout, 10.0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["url"], "http://api:8000/internal/workflows/wf1")
        self.assertEqual(
            self.requests[0]["headers"],
            {"Content-Type": "application/json", "x-internal-token": "tok"},
        )

    async def test_returns_bare_definition_payload(self) -> None:
        self.install(200, dict(DEFINITION))

        result = await activities.load_workflow("wf2")

        self.assertEqual(result, DEFINITION)

    async def test_non_200_raises(self) -> None:
        self.install(404, {"detail": "not found"})

        with self.assertRaises(RuntimeError) as ctx:
            await activities.load_workflow("wf1")
        self.assertEqual(str(ctx.exception), "workflow 'wf1' fetch returned HTTP 404")

    async def test_response_without_definition_raises(self) -> None:
        self.install(200, {"irrelevant": True})

        with self.assertRaises(RuntimeError) as ctx:
            await activities.load_workflow("wf1")
        self.assertEqual(str(ctx.exception), "workflow 'wf1' response contained no definition")

    async def test_token_header_omitted_when_unset(self) -> None:
        self.install(200, {"definition": dict(DEFINITION)}, token=None)

        result = await activities.load_workflow("wf1")

        self.assertEqual(result, DEFINITION)
        self.assertEqual(self.requests[0]["headers"], {"Content-Type": "application/json"})


if __name__ == "__main__":
    unittest.main()
