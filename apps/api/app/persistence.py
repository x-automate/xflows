from __future__ import annotations

import logging

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
    definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
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
    occurred_at TIMESTAMPTZ NOT NULL
);

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


async def _create_postgres_store(settings: Settings) -> PostgresStore:
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
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
