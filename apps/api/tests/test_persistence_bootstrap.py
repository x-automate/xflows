"""Startup behaviour when Postgres is not reachable.

A database host that does not resolve used to kill startup with a bare
``socket.gaierror`` at the bottom of a 30-line asyncpg traceback, naming neither
the host it tried nor the setting to change. These tests pin the two things that
replaced it: a bounded retry, and a redacted, actionable message.
"""

from __future__ import annotations

import socket
import unittest
from unittest import mock

import asyncpg

from app.config import Settings
from app.persistence import _connect_failure_hint, create_store, describe_dsn
from app.store import InMemoryStore

DSN = "postgresql://xflows:sup3r-s3cret@postgres:5432/xflows"


def _settings(**overrides) -> Settings:
    base = {
        "database_url": DSN,
        "persistence_mode": "postgres",
        "schema_auto_migrate": False,
        "db_connect_max_attempts": 3,
        "db_connect_backoff_s": 0.0,
    }
    base.update(overrides)
    return Settings(**base)


class DescribeDsnTests(unittest.TestCase):
    def test_reports_target_without_credentials(self) -> None:
        described = describe_dsn(DSN)
        self.assertEqual(described, "postgres:5432/xflows")
        self.assertNotIn("sup3r-s3cret", described)
        self.assertNotIn("xflows:sup3r", described)

    def test_defaults_the_port_and_tolerates_a_bare_dsn(self) -> None:
        self.assertEqual(describe_dsn("postgresql://db/app"), "db:5432/app")
        self.assertEqual(describe_dsn("postgresql://db:6543/"), "db:6543/<no database>")
        # A value that is not a DSN has no database name to report, and echoing
        # its "path" back would only mislead.
        self.assertEqual(describe_dsn("not a dsn"), "<unparseable DATABASE_URL>")
        self.assertEqual(describe_dsn(""), "<unparseable DATABASE_URL>")


class ConnectFailureHintTests(unittest.TestCase):
    def test_never_leaks_the_password(self) -> None:
        for error in (
            socket.gaierror(-2, "Name or service not known"),
            ConnectionRefusedError("refused"),
            asyncpg.InvalidAuthorizationSpecificationError("nope"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertNotIn("sup3r-s3cret", _connect_failure_hint(DSN, error))

    def test_unresolvable_host_points_at_database_url(self) -> None:
        hint = _connect_failure_hint(DSN, socket.gaierror(-2, "Name or service not known"))
        self.assertIn("postgres:5432/xflows", hint)
        self.assertIn("does not resolve", hint)
        self.assertIn("DATABASE_URL", hint)
        self.assertIn("PERSISTENCE_MODE=memory", hint)

    def test_refused_connection_and_bad_credentials_differ(self) -> None:
        refused = _connect_failure_hint(DSN, ConnectionRefusedError("refused"))
        self.assertIn("refused the connection", refused)
        auth = _connect_failure_hint(DSN, asyncpg.InvalidAuthorizationSpecificationError("nope"))
        self.assertIn("credentials", auth)
        self.assertIn("postgres_data volume", auth)


class ConnectRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovers_when_the_database_arrives_late(self) -> None:
        pool = mock.MagicMock()
        attempts = []

        async def create_pool(dsn, **kwargs):
            attempts.append(dsn)
            if len(attempts) < 3:
                raise socket.gaierror(-2, "Name or service not known")
            return pool

        with mock.patch("app.persistence.asyncpg.create_pool", side_effect=create_pool):
            with mock.patch("app.persistence._create_redis", return_value=None):
                store = await create_store(_settings())

        self.assertEqual(len(attempts), 3)
        self.assertIs(store.pool, pool)

    async def test_gives_up_with_an_actionable_message(self) -> None:
        async def create_pool(dsn, **kwargs):
            raise socket.gaierror(-2, "Name or service not known")

        with mock.patch("app.persistence.asyncpg.create_pool", side_effect=create_pool):
            with self.assertRaises(RuntimeError) as caught:
                await create_store(_settings())

        message = str(caught.exception)
        self.assertIn("postgres:5432/xflows", message)
        self.assertIn("does not resolve", message)
        self.assertNotIn("sup3r-s3cret", message)
        # The original error stays attached for anyone reading the traceback.
        self.assertIsInstance(caught.exception.__cause__, socket.gaierror)

    async def test_memory_mode_never_touches_the_database(self) -> None:
        with mock.patch("app.persistence.asyncpg.create_pool") as create_pool:
            store = await create_store(_settings(persistence_mode="memory"))
        create_pool.assert_not_called()
        self.assertIsInstance(store, InMemoryStore)

    async def test_bad_credentials_fail_fast_instead_of_waiting_out_the_backoff(self) -> None:
        calls = []

        async def create_pool(dsn, **kwargs):
            calls.append(dsn)
            raise asyncpg.InvalidAuthorizationSpecificationError("password authentication failed")

        with mock.patch("app.persistence.asyncpg.create_pool", side_effect=create_pool):
            with self.assertRaises(RuntimeError) as caught:
                await create_store(_settings(db_connect_max_attempts=5))

        # Configuration, not a startup race — no point retrying it five times.
        self.assertEqual(len(calls), 1)
        self.assertIn("credentials", str(caught.exception))

    async def test_a_missing_database_also_fails_fast(self) -> None:
        calls = []

        async def create_pool(dsn, **kwargs):
            calls.append(dsn)
            raise asyncpg.InvalidCatalogNameError('database "xflows" does not exist')

        with mock.patch("app.persistence.asyncpg.create_pool", side_effect=create_pool):
            with self.assertRaises(RuntimeError):
                await create_store(_settings(db_connect_max_attempts=5))
        self.assertEqual(len(calls), 1)

    async def test_a_single_attempt_is_honoured(self) -> None:
        calls = []

        async def create_pool(dsn, **kwargs):
            calls.append(dsn)
            raise ConnectionRefusedError("refused")

        with mock.patch("app.persistence.asyncpg.create_pool", side_effect=create_pool):
            with self.assertRaises(RuntimeError):
                await create_store(_settings(db_connect_max_attempts=1))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
