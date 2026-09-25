from __future__ import annotations

import asyncio
import logging
import socket
from urllib.parse import urlsplit

import asyncpg
from redis.asyncio import Redis

from .config import Settings
from .store import BaseStore, DualWriteStore, InMemoryStore, PostgresStore

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    auth_provider TEXT NOT NULL DEFAULT 'local',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    owner_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT NULL,
    graph JSONB NOT NULL DEFAULT '{"nodes": [], "edges": []}'::jsonb,
    configs JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_run JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    durable BOOLEAN NOT NULL DEFAULT FALSE,
    definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE workflows ADD COLUMN IF NOT EXISTS durable BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS project_secrets (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS triggers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NULL REFERENCES projects(id) ON DELETE SET NULL,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    workflow_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT NULL,
    error TEXT NULL,
    trace_id TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    node_id TEXT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    trace_id TEXT NULL,
    event_key TEXT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE run_events ADD COLUMN IF NOT EXISTS event_key TEXT NULL;

CREATE TABLE IF NOT EXISTS idempotency_keys (
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workflow_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflows_project_id ON workflows(project_id);
CREATE INDEX IF NOT EXISTS idx_workflows_created_at ON workflows(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_project_id ON runs(project_id);
CREATE INDEX IF NOT EXISTS idx_runs_workflow_id ON runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_runs_started_created ON runs(COALESCE(started_at, created_at) DESC);
CREATE INDEX IF NOT EXISTS idx_run_events_run_id_id ON run_events(run_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_events_run_event_key ON run_events (run_id, event_key) WHERE event_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_idempotency_expiry ON idempotency_keys(expires_at);
"""


async def _create_redis(url: str) -> Redis | None:
    try:
        client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:  # pragma: no cover - connectivity branch
        logger.warning("Redis unavailable, continuing without cache: %s", exc)
        return None


def describe_dsn(dsn: str) -> str:
    """``host:port/database`` for logs — never the user or password."""
    try:
        parts = urlsplit(dsn)
        host = parts.hostname
        port = parts.port or 5432
    except ValueError:
        return "<unparseable DATABASE_URL>"
    if not host:
        # No authority component: the value is not a DSN at all, so its "path" is
        # not a database name and echoing it back would only mislead.
        return "<unparseable DATABASE_URL>"
    database = (parts.path or "").lstrip("/") or "<no database>"
    return f"{host}:{port}/{database}"


def _connect_failure_hint(dsn: str, error: BaseException) -> str:
    """Turn an asyncpg connection failure into something worth acting on."""
    target = describe_dsn(dsn)
    host = urlsplit(dsn).hostname or "<no host>"
    if isinstance(error, socket.gaierror):
        cause = f"the host name {host!r} does not resolve"
        remedies = (
            f"Check DATABASE_URL. Inside docker compose the host must be the service name "
            f"('postgres'), and the API has to be on the same compose project — "
            f"`docker compose --profile core up` starts both. Running the API outside "
            f"compose (a bare `uvicorn`, or a container started with `docker run`) cannot "
            f"resolve {host!r}: point DATABASE_URL at a reachable host such as "
            f"localhost:5432, or set PERSISTENCE_MODE=memory for a throwaway instance."
        )
    elif isinstance(error, (ConnectionRefusedError, OSError)):
        cause = "the host resolved but refused the connection"
        remedies = (
            "Postgres is probably not accepting connections yet, or the port is wrong. "
            "Check that the database container is healthy and that DATABASE_URL's port "
            "matches the one it publishes."
        )
    elif isinstance(error, asyncpg.InvalidAuthorizationSpecificationError):
        cause = "the server rejected the credentials"
        remedies = (
            "Check POSTGRES_USER / POSTGRES_PASSWORD against the values the database was "
            "initialised with. An existing postgres_data volume keeps the original "
            "credentials even after you change the .env."
        )
    else:
        cause = f"{type(error).__name__}: {error}"
        remedies = "Check DATABASE_URL and that the database is reachable from this container."
    return f"Cannot reach Postgres at {target} — {cause}. {remedies}"


# Retrying these is pointless: bad credentials or a missing database are
# configuration, not a startup race, and waiting out the backoff only delays
# the message that says so.
_NON_RETRYABLE = (
    asyncpg.InvalidAuthorizationSpecificationError,
    asyncpg.InvalidCatalogNameError,
    asyncpg.InsufficientPrivilegeError,
)


async def _connect_pool(settings: Settings) -> asyncpg.Pool:
    """Open the pool, retrying while the database is still coming up.

    Startup order is a race in every container runtime: compose's
    ``depends_on: service_healthy`` covers the happy path, but a bare
    ``docker run``, a Kubernetes rollout or a database restart all land here with
    the DB briefly unreachable. Retrying a few times costs seconds; failing
    immediately costs a container restart loop.
    """
    attempts = max(1, settings.db_connect_max_attempts)
    backoff = max(0.0, settings.db_connect_backoff_s)
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = exc
            if attempt == attempts or isinstance(exc, _NON_RETRYABLE):
                break
            delay = backoff * (2 ** (attempt - 1))
            logger.warning(
                "Postgres not reachable at %s (attempt %d/%d): %s — retrying in %.1fs",
                describe_dsn(settings.database_url),
                attempt,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    message = _connect_failure_hint(settings.database_url, last_error)
    logger.error("%s", message)
    raise RuntimeError(message) from last_error


async def _create_postgres_store(settings: Settings) -> PostgresStore:
    pool = await _connect_pool(settings)
    logger.info("Connected to Postgres at %s", describe_dsn(settings.database_url))
    if settings.schema_auto_migrate:
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
    redis = await _create_redis(settings.redis_url)
    return PostgresStore(
        pool=pool,
        redis=redis,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        idempotency_ttl_seconds=settings.idempotency_ttl_seconds,
    )


async def create_store(settings: Settings) -> BaseStore:
    mode = settings.persistence_mode.lower()
    if mode == "memory":
        return InMemoryStore()

    sql_store = await _create_postgres_store(settings)
    if mode == "postgres":
        return sql_store

    if mode == "dual":
        memory = InMemoryStore()
        return DualWriteStore(memory=memory, sql=sql_store, reads_from_sql=settings.persistence_reads_from_sql)

    logger.warning("Unknown persistence mode '%s', falling back to postgres", mode)
    return sql_store
