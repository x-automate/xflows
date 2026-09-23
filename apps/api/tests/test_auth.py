"""Wave 4 tests: API authN/authZ (XU-7, XF-04)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

CALLERS = (
    "owner|tok-owner|owner|*"
    ",reviewer|tok-rev|reviewer|*"
    ",operator|tok-op|operator|*"
    ",scoped-rev|tok-sc|reviewer|p2"
)


def _make_app():
    import app.main as main_module
    from app.config import settings

    settings.auth_mode = "token"
    settings.api_callers = CALLERS
    settings.persistence_mode = "memory"
    settings.internal_api_tokens = "tok-worker"
    settings.trigger_scheduler_interval_s = 0  # no scheduler in tests
    main_module.temporal_gateway = _FakeGateway(connected=True)
    return main_module


class _FakeGateway:
    def __init__(self, connected: bool = True) -> None:
        self.connected_flag = connected
        self.started: list[dict] = []
        self.signals: list[tuple[str, str, dict]] = []

    async def connect(self):
        from types import SimpleNamespace

        return SimpleNamespace(connected=self.connected_flag, reason=None if self.connected_flag else "no server")

    async def start_workflow(self, **kwargs):
        from types import SimpleNamespace

        status = SimpleNamespace(connected=self.connected_flag, reason=None)
        if self.connected_flag:
            self.started.append(kwargs)
        return status

    async def signal_workflow(self, handle_id: str, signal_name: str, payload):
        self.signals.append((handle_id, signal_name, payload))
        from types import SimpleNamespace

        return SimpleNamespace(connected=True, reason=None)


class CallerParsingTests(unittest.TestCase):
    def test_parse_callers_roles_and_scopes(self) -> None:
        from app.auth import parse_callers

        callers = parse_callers(CALLERS)
        self.assertEqual(set(callers), {"tok-owner", "tok-rev", "tok-op", "tok-sc"})
        self.assertEqual(callers["tok-sc"].role, "reviewer")
        self.assertEqual(callers["tok-sc"].projects, frozenset({"p2"}))
        self.assertIsNone(callers["tok-owner"].projects)
        self.assertEqual(callers["tok-op"].rank, 1)
        self.assertEqual(callers["tok-rev"].rank, 2)
        self.assertEqual(callers["tok-owner"].rank, 3)

    def test_malformed_entries_skipped(self) -> None:
        from app.auth import parse_callers

        callers = parse_callers("bad-entry,tok|tok|bogusrole|*,tok2|tok2|owner")
        self.assertEqual(set(callers), {"tok2"})


class AuthEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        main_module = _make_app()
        self.main = main_module
        self._client_cm = TestClient(main_module.app)
        self.client = self._client_cm.__enter__()
        self.main = main_module

    def tearDown(self) -> None:
        self._client_cm.__exit__(None, None, None)

    def _headers(self, token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def test_missing_token_is_401(self) -> None:
        response = self.client.get("/projects")
        self.assertEqual(response.status_code, 401)

    def test_unknown_token_is_401(self) -> None:
        response = self.client.get("/projects", headers=self._headers("bogus"))
        self.assertEqual(response.status_code, 401)

    def test_operator_cannot_create_users(self) -> None:
        response = self.client.post(
            "/users",
            json={"email": "a@b.c", "name": "A"},
            headers=self._headers("tok-op"),
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_can_create_project(self) -> None:
        response = self.client.post(
            "/projects",
            json={"id": "p1", "name": "P1"},
            headers=self._headers("tok-owner"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "p1")

    def test_project_scope_blocks_foreign_project(self) -> None:
        # owner creates p1; scoped reviewer may only see p2
        self.client.post("/projects", json={"id": "p1", "name": "P1"}, headers=self._headers("tok-owner"))
        denied = self.client.get("/projects/p1", headers=self._headers("tok-sc"))
        self.assertEqual(denied.status_code, 403)

    def test_health_and_metrics_stay_open(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/metrics").status_code, 200)

    def test_auth_off_authenticates_anonymous_owner(self) -> None:
        from app.config import settings

        settings.auth_mode = "off"
        try:
            response = self.client.post("/projects", json={"id": "p9", "name": "P9"})
            self.assertEqual(response.status_code, 200)
        finally:
            settings.auth_mode = "token"


if __name__ == "__main__":
    unittest.main()
