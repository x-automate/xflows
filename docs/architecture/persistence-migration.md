# Persistence Migration Plan

## Objective

Move application data from the in-memory API store to durable Postgres tables while keeping the same API contracts.

## Target Entities

- `projects(id uuid primary key, name text, created_at timestamptz, updated_at timestamptz)`
- `workflows(id text primary key, project_id uuid, version int, status text, definition jsonb, created_at timestamptz, updated_at timestamptz)`
- `triggers(id text primary key, project_id uuid, type text, enabled bool, config jsonb, created_at timestamptz, updated_at timestamptz)`
- `runs(id text primary key, project_id uuid, workflow_id text, workflow_version int, status text, input text, output text, error text, trace_id text, started_at timestamptz, finished_at timestamptz)`
- `run_events(id bigserial primary key, run_id text, node_id text, event_type text, payload jsonb, trace_id text, occurred_at timestamptz)`

## Rollout Stages

1. Add repository interfaces around existing in-memory store methods.
2. Introduce SQL-backed repository implementation in parallel.
3. Dual-write run lifecycle events to in-memory + SQL during validation.
4. Switch reads to SQL repositories behind a feature flag.
5. Remove in-memory store from production path once parity metrics are stable.

## Migration Safety

- Keep idempotency index in Redis/Postgres unique constraints.
- Use monotonic event ordering (`run_events.id`) to support SSE resume cursors.
- Backfill historical runs from in-memory snapshots in lower environments only.
