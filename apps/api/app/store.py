from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import blake2b
from uuid import uuid4

import asyncpg
from redis.asyncio import Redis

from .models import (
    ProjectCreateRequest,
    ProjectRecord,
    ProjectUpdateRequest,
    RunEvent,
    RunRecord,
    TriggerCreateRequest,
    TriggerRecord,
    TriggerUpdateRequest,
    UserCreateRequest,
    UserRecord,
    WorkflowCreateRequest,
    WorkflowRecord,
)

DEFAULT_CONFIGS = {
    "hasOpenAIKey": False,
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "maxTokens": 512,
}
DEFAULT_GRAPH = {"nodes": [], "edges": []}


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _decode_json_maybe(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _decode_json_object(value: object, default: dict) -> dict:
    parsed = _decode_json_maybe(value)
    if isinstance(parsed, dict):
        return parsed
    return default.copy()


def _advisory_key(value: str) -> int:
    return int.from_bytes(blake2b(value.encode("utf-8"), digest_size=8).digest(), "big", signed=True)


class BaseStore(ABC):
    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def create_user(self, payload: UserCreateRequest) -> UserRecord: ...

    @abstractmethod
    async def get_user(self, user_id: str) -> UserRecord | None: ...

    @abstractmethod
    async def list_users(self) -> list[UserRecord]: ...

    @abstractmethod
    async def create_project(self, payload: ProjectCreateRequest) -> ProjectRecord: ...

    @abstractmethod
    async def ensure_project(self, project_id: str, name: str | None = None) -> ProjectRecord: ...

    @abstractmethod
    async def list_projects(self) -> list[ProjectRecord]: ...

    @abstractmethod
    async def get_project(self, project_id: str) -> ProjectRecord | None: ...

    @abstractmethod
    async def update_project(self, project_id: str, payload: ProjectUpdateRequest) -> ProjectRecord | None: ...

    @abstractmethod
    async def create_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord: ...

    @abstractmethod
    async def upsert_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord: ...

    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> WorkflowRecord | None: ...

    @abstractmethod
    async def list_workflows(self) -> list[WorkflowRecord]: ...

    @abstractmethod
    async def create_run(
        self,
        workflow_id: str,
        workflow_version: int,
        user_input: str,
        trace_id: str | None,
        project_id: str | None = None,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord: ...

    @abstractmethod
    async def get_run(self, run_id: str) -> RunRecord | None: ...

    @abstractmethod
    async def list_runs(self, project_id: str | None = None) -> list[RunRecord]: ...

    @abstractmethod
    async def update_run(self, run: RunRecord) -> RunRecord: ...

    @abstractmethod
    async def append_event(self, event: RunEvent) -> RunEvent: ...

    @abstractmethod
    async def get_events(
        self, run_id: str, *, after_id: int | None = None, limit: int = 500
    ) -> list[RunEvent]: ...

    @abstractmethod
    async def list_triggers(self, project_id: str) -> list[TriggerRecord]: ...

    @abstractmethod
    async def create_trigger(self, project_id: str, payload: TriggerCreateRequest) -> TriggerRecord: ...

    @abstractmethod
    async def update_trigger(
        self, project_id: str, trigger_id: str, payload: TriggerUpdateRequest
    ) -> TriggerRecord | None: ...


class InMemoryStore(BaseStore):
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.projects: dict[str, ProjectRecord] = {}
        self.workflows: dict[str, WorkflowRecord] = {}
        self.runs: dict[str, RunRecord] = {}
        self.run_events: dict[str, list[RunEvent]] = defaultdict(list)
        self.triggers: dict[str, dict[str, TriggerRecord]] = defaultdict(dict)
        self.idempotency_index: dict[tuple[str, str], str] = {}
        self._event_counter = 0

    async def close(self) -> None:
        return None

    async def create_user(self, payload: UserCreateRequest) -> UserRecord:
        now = utc_now()
        user = UserRecord(
            id=str(uuid4()),
            email=payload.email.lower().strip(),
            name=payload.name.strip(),
            authProvider=payload.authProvider,
            createdAt=now,
            updatedAt=now,
        )
        self.users[user.id] = user
        return user

    async def get_user(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    async def list_users(self) -> list[UserRecord]:
        return sorted(self.users.values(), key=lambda item: item.createdAt, reverse=True)

    async def create_project(self, payload: ProjectCreateRequest) -> ProjectRecord:
        now = utc_now()
        project = ProjectRecord(
            id=payload.id or str(uuid4()),
            name=payload.name.strip() or "Untitled Project",
            description=payload.description,
            graph=DEFAULT_GRAPH.copy(),
            configs=DEFAULT_CONFIGS.copy(),
            createdAt=now,
            updatedAt=now,
        )
        self.projects[project.id] = project
        return project

    async def ensure_project(self, project_id: str, name: str | None = None) -> ProjectRecord:
        existing = self.projects.get(project_id)
        if existing:
            return existing
        now = utc_now()
        project = ProjectRecord(
            id=project_id,
            name=(name or project_id).strip() or "Untitled Project",
            graph=DEFAULT_GRAPH.copy(),
            configs=DEFAULT_CONFIGS.copy(),
            createdAt=now,
            updatedAt=now,
        )
        self.projects[project.id] = project
        return project

    async def list_projects(self) -> list[ProjectRecord]:
        return sorted(self.projects.values(), key=lambda item: item.updatedAt, reverse=True)

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        return self.projects.get(project_id)

    async def update_project(self, project_id: str, payload: ProjectUpdateRequest) -> ProjectRecord | None:
        project = self.projects.get(project_id)
        if not project:
            return None
        changes = payload.model_dump(exclude_unset=True)
        updated = project.model_copy(update=changes | {"updatedAt": utc_now()})
        self.projects[project_id] = updated
        return updated

    async def create_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord:
        now = utc_now()
        workflow = WorkflowRecord(
            id=payload.id,
            name=payload.name,
            description=payload.description,
            version=1,
            status="draft",
            nodes=payload.nodes,
            edges=payload.edges,
            metadata=payload.metadata,
            createdAt=now,
            updatedAt=now,
        )
        self.workflows[workflow.id] = workflow
        return workflow

    async def upsert_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord:
        existing = await self.get_workflow(payload.id)
        if existing:
            updated = existing.model_copy(
                update={
                    "name": payload.name,
                    "description": payload.description,
                    "nodes": payload.nodes,
                    "edges": payload.edges,
                    "metadata": payload.metadata,
                    "updatedAt": utc_now(),
                }
            )
            self.workflows[existing.id] = updated
            return updated
        return await self.create_workflow(payload)

    async def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        return self.workflows.get(workflow_id)

    async def list_workflows(self) -> list[WorkflowRecord]:
        return sorted(self.workflows.values(), key=lambda item: item.createdAt, reverse=True)

    async def create_run(
        self,
        workflow_id: str,
        workflow_version: int,
        user_input: str,
        trace_id: str | None,
        project_id: str | None = None,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        if idempotency_key:
            existing = self.idempotency_index.get((workflow_id, idempotency_key))
            if existing:
                found = self.runs.get(existing)
                if found:
                    return found
        run = RunRecord(
            id=f"run_{uuid4().hex[:16]}",
            projectId=project_id,
            workflowId=workflow_id,
            workflowVersion=workflow_version,
            status="queued",
            input=user_input,
            traceId=trace_id,
            metadata=metadata or {},
        )
        self.runs[run.id] = run
        if idempotency_key:
            self.idempotency_index[(workflow_id, idempotency_key)] = run.id
        return run

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    async def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        items = self.runs.values()
        if project_id:
            items = [run for run in items if run.projectId == project_id]
        return sorted(items, key=lambda item: item.startedAt or utc_now(), reverse=True)

    async def update_run(self, run: RunRecord) -> RunRecord:
        self.runs[run.id] = run
        return run

    async def append_event(self, event: RunEvent) -> RunEvent:
        self._event_counter += 1
        with_id = event.model_copy(update={"id": self._event_counter})
        self.run_events[event.runId].append(with_id)
        return with_id

    async def get_events(
        self, run_id: str, *, after_id: int | None = None, limit: int = 500
    ) -> list[RunEvent]:
        events = self.run_events.get(run_id, [])
        if after_id is not None:
            events = [event for event in events if (event.id or 0) > after_id]
        return events[:limit]

    async def list_triggers(self, project_id: str) -> list[TriggerRecord]:
        return sorted(self.triggers.get(project_id, {}).values(), key=lambda item: item.createdAt)

    async def create_trigger(self, project_id: str, payload: TriggerCreateRequest) -> TriggerRecord:
        now = utc_now()
        trigger = TriggerRecord(
            id=f"trg_{uuid4().hex[:10]}",
            projectId=project_id,
            type=payload.type,
            enabled=payload.enabled,
            config=payload.config,
            createdAt=now,
            updatedAt=now,
        )
        self.triggers[project_id][trigger.id] = trigger
        return trigger

    async def update_trigger(
        self, project_id: str, trigger_id: str, payload: TriggerUpdateRequest
    ) -> TriggerRecord | None:
        trigger = self.triggers.get(project_id, {}).get(trigger_id)
        if not trigger:
            return None
        updated = trigger.model_copy(
            update={
                "enabled": payload.enabled if payload.enabled is not None else trigger.enabled,
                "config": payload.config if payload.config is not None else trigger.config,
                "updatedAt": utc_now(),
            }
        )
        self.triggers[project_id][trigger.id] = updated
        return updated


class PostgresStore(BaseStore):
    def __init__(
        self,
        pool: asyncpg.Pool,
        redis: Redis | None,
        *,
        cache_ttl_seconds: int = 30,
        idempotency_ttl_seconds: int = 86400,
    ) -> None:
        self.pool = pool
        self.redis = redis
        self.cache_ttl_seconds = cache_ttl_seconds
        self.idempotency_ttl_seconds = idempotency_ttl_seconds

    async def close(self) -> None:
        await self.pool.close()
        if self.redis:
            await self.redis.aclose()

    async def create_user(self, payload: UserCreateRequest) -> UserRecord:
        now = utc_now()
        row = await self.pool.fetchrow(
            """
            INSERT INTO users (id, email, name, auth_provider, created_at, updated_at)
            VALUES ($1::uuid, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            str(uuid4()),
            payload.email.lower().strip(),
            payload.name.strip(),
            payload.authProvider,
            now,
            now,
        )
        return UserRecord(
            id=str(row["id"]),
            email=row["email"],
            name=row["name"],
            authProvider=row["auth_provider"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    async def get_user(self, user_id: str) -> UserRecord | None:
        row = await self.pool.fetchrow("SELECT * FROM users WHERE id = $1::uuid", user_id)
        if not row:
            return None
        return UserRecord(
            id=str(row["id"]),
            email=row["email"],
            name=row["name"],
            authProvider=row["auth_provider"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    async def list_users(self) -> list[UserRecord]:
        rows = await self.pool.fetch("SELECT * FROM users ORDER BY created_at DESC")
        return [
            UserRecord(
                id=str(row["id"]),
                email=row["email"],
                name=row["name"],
                authProvider=row["auth_provider"],
                createdAt=row["created_at"],
                updatedAt=row["updated_at"],
            )
            for row in rows
        ]

    async def _cache_get(self, key: str) -> dict | list | None:
        if not self.redis:
            return None
        raw = await self.redis.get(key)
        if not raw:
            return None
        return json.loads(raw)

    async def _cache_set(self, key: str, value: dict | list) -> None:
        if not self.redis:
            return
        await self.redis.setex(key, self.cache_ttl_seconds, json.dumps(value, default=str))

    async def _cache_delete_many(self, *keys: str) -> None:
        if not self.redis or not keys:
            return
        await self.redis.delete(*keys)

    async def _invalidate_project_cache(self, project_id: str) -> None:
        await self._cache_delete_many(f"project:{project_id}", "projects:list")

    @staticmethod
    def _project_row_to_record(row: asyncpg.Record) -> ProjectRecord:
        graph = _decode_json_object(row["graph"], DEFAULT_GRAPH)
        configs = _decode_json_object(row["configs"], DEFAULT_CONFIGS)
        metadata = _decode_json_object(row["metadata"], {})
        last_run = _decode_json_maybe(row["last_run"])
        return ProjectRecord(
            id=row["id"],
            ownerUserId=row["owner_user_id"],
            name=row["name"],
            description=row["description"],
            graph=graph,
            configs=configs,
            metadata=metadata,
            lastRun=last_run if isinstance(last_run, dict) else None,
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    @staticmethod
    def _workflow_row_to_record(row: asyncpg.Record) -> WorkflowRecord:
        definition = _decode_json_object(row["definition"], {})
        return WorkflowRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            version=row["version"],
            status=row["status"],
            nodes=definition.get("nodes", []),
            edges=definition.get("edges", []),
            metadata=definition.get("metadata", {}),
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    @staticmethod
    def _run_row_to_record(row: asyncpg.Record) -> RunRecord:
        metadata = _decode_json_object(row["metadata"], {})
        return RunRecord(
            id=row["id"],
            projectId=row["project_id"],
            workflowId=row["workflow_id"],
            workflowVersion=row["workflow_version"],
            status=row["status"],
            input=row["input"],
            output=row["output"],
            error=row["error"],
            traceId=row["trace_id"],
            metadata=metadata,
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
        )

    @staticmethod
    def _event_row_to_record(row: asyncpg.Record) -> RunEvent:
        payload = _decode_json_object(row["payload"], {})
        return RunEvent(
            id=row["id"],
            runId=row["run_id"],
            type=row["event_type"],
            nodeId=row["node_id"],
            payload=payload,
            timestamp=row["occurred_at"],
            traceId=row["trace_id"],
        )

    async def create_project(self, payload: ProjectCreateRequest) -> ProjectRecord:
        now = utc_now()
        project_id = payload.id or str(uuid4())
        row = await self.pool.fetchrow(
            """
            INSERT INTO projects (id, name, description, graph, configs, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, '{}'::jsonb, $6, $7)
            RETURNING *
            """,
            project_id,
            payload.name.strip() or "Untitled Project",
            payload.description,
            json.dumps(DEFAULT_GRAPH),
            json.dumps(DEFAULT_CONFIGS),
            now,
            now,
        )
        await self._invalidate_project_cache(project_id)
        return self._project_row_to_record(row)

    async def ensure_project(self, project_id: str, name: str | None = None) -> ProjectRecord:
        existing = await self.get_project(project_id)
        if existing:
            return existing
        now = utc_now()
        row = await self.pool.fetchrow(
            """
            INSERT INTO projects (id, name, graph, configs, metadata, created_at, updated_at)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, '{}'::jsonb, $5, $6)
            ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            project_id,
            (name or project_id).strip() or "Untitled Project",
            json.dumps(DEFAULT_GRAPH),
            json.dumps(DEFAULT_CONFIGS),
            now,
            now,
        )
        await self._invalidate_project_cache(project_id)
        return self._project_row_to_record(row)

    async def list_projects(self) -> list[ProjectRecord]:
        cached = await self._cache_get("projects:list")
        if cached is not None:
            return [ProjectRecord.model_validate(item) for item in cached]
        rows = await self.pool.fetch("SELECT * FROM projects ORDER BY updated_at DESC")
        items = [self._project_row_to_record(row) for row in rows]
        await self._cache_set("projects:list", [item.model_dump(mode="json") for item in items])
        return items

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        cache_key = f"project:{project_id}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return ProjectRecord.model_validate(cached)
        row = await self.pool.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
        if not row:
            return None
        project = self._project_row_to_record(row)
        await self._cache_set(cache_key, project.model_dump(mode="json"))
        return project

    async def update_project(self, project_id: str, payload: ProjectUpdateRequest) -> ProjectRecord | None:
        existing = await self.get_project(project_id)
        if not existing:
            return None
        patch = payload.model_dump(exclude_unset=True)
        merged = existing.model_copy(
            update={
                **patch,
                "updatedAt": utc_now(),
            }
        )
        row = await self.pool.fetchrow(
            """
            UPDATE projects
            SET name = $2,
                description = $3,
                graph = $4::jsonb,
                configs = $5::jsonb,
                metadata = $6::jsonb,
                last_run = $7::jsonb,
                updated_at = $8
            WHERE id = $1
            RETURNING *
            """,
            project_id,
            merged.name,
            merged.description,
            json.dumps(merged.graph),
            json.dumps(merged.configs),
            json.dumps(merged.metadata),
            json.dumps(merged.lastRun),
            merged.updatedAt,
        )
        if not row:
            return None
        await self._invalidate_project_cache(project_id)
        return self._project_row_to_record(row)

    async def create_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord:
        now = utc_now()
        project_id = payload.metadata.get("projectId")
        row = await self.pool.fetchrow(
            """
            INSERT INTO workflows (
                id, project_id, name, description, version, status, definition, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 1, 'draft', $5::jsonb, $6, $7)
            RETURNING *
            """,
            payload.id,
            project_id,
            payload.name,
            payload.description,
            json.dumps(
                {
                    "nodes": [node.model_dump(mode="json") for node in payload.nodes],
                    "edges": [edge.model_dump(mode="json") for edge in payload.edges],
                    "metadata": payload.metadata,
                }
            ),
            now,
            now,
        )
        return self._workflow_row_to_record(row)

    async def upsert_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord:
        now = utc_now()
        project_id = payload.metadata.get("projectId")
        row = await self.pool.fetchrow(
            """
            INSERT INTO workflows (
                id, project_id, name, description, version, status, definition, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, 1, 'draft', $5::jsonb, $6, $7)
            ON CONFLICT (id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                definition = EXCLUDED.definition,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            payload.id,
            project_id,
            payload.name,
            payload.description,
            json.dumps(
                {
                    "nodes": [node.model_dump(mode="json") for node in payload.nodes],
                    "edges": [edge.model_dump(mode="json") for edge in payload.edges],
                    "metadata": payload.metadata,
                }
            ),
            now,
            now,
        )
        return self._workflow_row_to_record(row)

    async def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        row = await self.pool.fetchrow("SELECT * FROM workflows WHERE id = $1", workflow_id)
        return self._workflow_row_to_record(row) if row else None

    async def list_workflows(self) -> list[WorkflowRecord]:
        rows = await self.pool.fetch("SELECT * FROM workflows ORDER BY created_at DESC")
        return [self._workflow_row_to_record(row) for row in rows]

    async def create_run(
        self,
        workflow_id: str,
        workflow_version: int,
        user_input: str,
        trace_id: str | None,
        project_id: str | None = None,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        metadata_value = metadata or {}
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if idempotency_key:
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock($1)",
                        _advisory_key(f"{workflow_id}:{idempotency_key}"),
                    )
                    existing_id = await conn.fetchval(
                        """
                        SELECT run_id
                        FROM idempotency_keys
                        WHERE workflow_id = $1
                          AND idempotency_key = $2
                          AND expires_at > NOW()
                        """,
                        workflow_id,
                        idempotency_key,
                    )
                    if existing_id:
                        existing = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", existing_id)
                        if existing:
                            return self._run_row_to_record(existing)
                run_id = f"run_{uuid4().hex[:16]}"
                row = await conn.fetchrow(
                    """
                    INSERT INTO runs (
                        id, project_id, workflow_id, workflow_version, status, input, trace_id, metadata, created_at
                    )
                    VALUES ($1, $2, $3, $4, 'queued', $5, $6, $7::jsonb, NOW())
                    RETURNING *
                    """,
                    run_id,
                    project_id,
                    workflow_id,
                    workflow_version,
                    user_input,
                    trace_id,
                    json.dumps(metadata_value),
                )
                if idempotency_key:
                    await conn.execute(
                        """
                        INSERT INTO idempotency_keys (workflow_id, idempotency_key, run_id, expires_at)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (workflow_id, idempotency_key)
                        DO UPDATE SET run_id = EXCLUDED.run_id, expires_at = EXCLUDED.expires_at
                        """,
                        workflow_id,
                        idempotency_key,
                        run_id,
                        utc_now() + timedelta(seconds=self.idempotency_ttl_seconds),
                    )
                return self._run_row_to_record(row)

    async def get_run(self, run_id: str) -> RunRecord | None:
        cache_key = f"run:{run_id}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return RunRecord.model_validate(cached)
        row = await self.pool.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
        if not row:
            return None
        run = self._run_row_to_record(row)
        await self._cache_set(cache_key, run.model_dump(mode="json"))
        return run

    async def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        if project_id:
            rows = await self.pool.fetch(
                "SELECT * FROM runs WHERE project_id = $1 ORDER BY COALESCE(started_at, created_at) DESC",
                project_id,
            )
        else:
            rows = await self.pool.fetch("SELECT * FROM runs ORDER BY COALESCE(started_at, created_at) DESC")
        return [self._run_row_to_record(row) for row in rows]

    async def update_run(self, run: RunRecord) -> RunRecord:
        row = await self.pool.fetchrow(
            """
            UPDATE runs
            SET status = $2,
                output = $3,
                error = $4,
                trace_id = $5,
                metadata = $6::jsonb,
                started_at = $7,
                finished_at = $8
            WHERE id = $1
            RETURNING *
            """,
            run.id,
            run.status,
            run.output,
            run.error,
            run.traceId,
            json.dumps(run.metadata),
            run.startedAt,
            run.finishedAt,
        )
        updated = self._run_row_to_record(row)
        await self._cache_delete_many(f"run:{run.id}", f"runs:project:{run.projectId or 'all'}")
        return updated

    async def append_event(self, event: RunEvent) -> RunEvent:
        row = await self.pool.fetchrow(
            """
            INSERT INTO run_events (run_id, node_id, event_type, payload, trace_id, occurred_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            RETURNING *
            """,
            event.runId,
            event.nodeId,
            event.type,
            json.dumps(event.payload),
            event.traceId,
            event.timestamp,
        )
        return self._event_row_to_record(row)

    async def get_events(
        self, run_id: str, *, after_id: int | None = None, limit: int = 500
    ) -> list[RunEvent]:
        if after_id is None:
            rows = await self.pool.fetch(
                """
                SELECT * FROM run_events
                WHERE run_id = $1
                ORDER BY id ASC
                LIMIT $2
                """,
                run_id,
                limit,
            )
        else:
            rows = await self.pool.fetch(
                """
                SELECT * FROM run_events
                WHERE run_id = $1 AND id > $2
                ORDER BY id ASC
                LIMIT $3
                """,
                run_id,
                after_id,
                limit,
            )
        return [self._event_row_to_record(row) for row in rows]

    async def list_triggers(self, project_id: str) -> list[TriggerRecord]:
        rows = await self.pool.fetch(
            "SELECT * FROM triggers WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        return [
            TriggerRecord(
                id=row["id"],
                projectId=row["project_id"],
                type=row["type"],
                enabled=row["enabled"],
                config=_decode_json_object(row["config"], {}),
                createdAt=row["created_at"],
                updatedAt=row["updated_at"],
            )
            for row in rows
        ]

    async def create_trigger(self, project_id: str, payload: TriggerCreateRequest) -> TriggerRecord:
        now = utc_now()
        row = await self.pool.fetchrow(
            """
            INSERT INTO triggers (id, project_id, type, enabled, config, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
            RETURNING *
            """,
            f"trg_{uuid4().hex[:10]}",
            project_id,
            payload.type,
            payload.enabled,
            json.dumps(payload.config),
            now,
            now,
        )
        await self._invalidate_project_cache(project_id)
        return TriggerRecord(
            id=row["id"],
            projectId=row["project_id"],
            type=row["type"],
            enabled=row["enabled"],
            config=_decode_json_object(row["config"], {}),
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    async def update_trigger(
        self, project_id: str, trigger_id: str, payload: TriggerUpdateRequest
    ) -> TriggerRecord | None:
        row = await self.pool.fetchrow(
            """
            UPDATE triggers
            SET enabled = COALESCE($3, enabled),
                config = COALESCE($4::jsonb, config),
                updated_at = $5
            WHERE project_id = $1 AND id = $2
            RETURNING *
            """,
            project_id,
            trigger_id,
            payload.enabled,
            json.dumps(payload.config) if payload.config is not None else None,
            utc_now(),
        )
        if not row:
            return None
        await self._invalidate_project_cache(project_id)
        return TriggerRecord(
            id=row["id"],
            projectId=row["project_id"],
            type=row["type"],
            enabled=row["enabled"],
            config=_decode_json_object(row["config"], {}),
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )


class DualWriteStore(BaseStore):
    def __init__(self, memory: InMemoryStore, sql: PostgresStore, *, reads_from_sql: bool) -> None:
        self.memory = memory
        self.sql = sql
        self.reads_from_sql = reads_from_sql

    def _reader(self) -> BaseStore:
        return self.sql if self.reads_from_sql else self.memory

    async def close(self) -> None:
        await self.memory.close()
        await self.sql.close()

    async def create_user(self, payload: UserCreateRequest) -> UserRecord:
        user = await self.sql.create_user(payload)
        self.memory.users[user.id] = user
        return user if self.reads_from_sql else self.memory.users[user.id]

    async def get_user(self, user_id: str) -> UserRecord | None:
        return await self._reader().get_user(user_id)

    async def list_users(self) -> list[UserRecord]:
        return await self._reader().list_users()

    async def create_project(self, payload: ProjectCreateRequest) -> ProjectRecord:
        created = await self.memory.create_project(payload)
        await self.sql.ensure_project(created.id, created.name)
        if payload.description:
            await self.sql.update_project(created.id, ProjectUpdateRequest(description=payload.description))
        return await (self.sql.get_project(created.id) if self.reads_from_sql else self.memory.get_project(created.id))  # type: ignore[return-value]

    async def ensure_project(self, project_id: str, name: str | None = None) -> ProjectRecord:
        memory_project = await self.memory.ensure_project(project_id, name=name)
        await self.sql.ensure_project(project_id, name=name or memory_project.name)
        return await self._reader().ensure_project(project_id, name=name or memory_project.name)

    async def list_projects(self) -> list[ProjectRecord]:
        return await self._reader().list_projects()

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        return await self._reader().get_project(project_id)

    async def update_project(self, project_id: str, payload: ProjectUpdateRequest) -> ProjectRecord | None:
        await self.memory.update_project(project_id, payload)
        await self.sql.update_project(project_id, payload)
        return await self._reader().get_project(project_id)

    async def create_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord:
        created = await self.memory.create_workflow(payload)
        await self.sql.upsert_workflow(payload)
        return await self._reader().get_workflow(created.id) or created

    async def upsert_workflow(self, payload: WorkflowCreateRequest) -> WorkflowRecord:
        await self.memory.upsert_workflow(payload)
        await self.sql.upsert_workflow(payload)
        return await self._reader().get_workflow(payload.id) or await self.memory.get_workflow(payload.id)  # type: ignore[return-value]

    async def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        return await self._reader().get_workflow(workflow_id)

    async def list_workflows(self) -> list[WorkflowRecord]:
        return await self._reader().list_workflows()

    async def create_run(
        self,
        workflow_id: str,
        workflow_version: int,
        user_input: str,
        trace_id: str | None,
        project_id: str | None = None,
        metadata: dict | None = None,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        run = await self.sql.create_run(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            user_input=user_input,
            trace_id=trace_id,
            project_id=project_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        await self.memory.update_run(run)
        return run if self.reads_from_sql else (await self.memory.get_run(run.id) or run)

    async def get_run(self, run_id: str) -> RunRecord | None:
        return await self._reader().get_run(run_id)

    async def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        return await self._reader().list_runs(project_id)

    async def update_run(self, run: RunRecord) -> RunRecord:
        await self.memory.update_run(run)
        sql_run = await self.sql.update_run(run)
        return sql_run if self.reads_from_sql else run

    async def append_event(self, event: RunEvent) -> RunEvent:
        mem_event = await self.memory.append_event(event)
        sql_event = await self.sql.append_event(event)
        return sql_event if self.reads_from_sql else mem_event

    async def get_events(
        self, run_id: str, *, after_id: int | None = None, limit: int = 500
    ) -> list[RunEvent]:
        return await self._reader().get_events(run_id, after_id=after_id, limit=limit)

    async def list_triggers(self, project_id: str) -> list[TriggerRecord]:
        return await self._reader().list_triggers(project_id)

    async def create_trigger(self, project_id: str, payload: TriggerCreateRequest) -> TriggerRecord:
        memory_trigger = await self.memory.create_trigger(project_id, payload)
        sql_trigger = await self.sql.create_trigger(project_id, payload)
        return sql_trigger if self.reads_from_sql else memory_trigger

    async def update_trigger(
        self, project_id: str, trigger_id: str, payload: TriggerUpdateRequest
    ) -> TriggerRecord | None:
        memory_updated = await self.memory.update_trigger(project_id, trigger_id, payload)
        updated = await self.sql.update_trigger(project_id, trigger_id, payload)
        if self.reads_from_sql:
            return updated
        return memory_updated
