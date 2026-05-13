# XFlows API

FastAPI gateway for workflow management and run orchestration.

## Responsibilities

- Workflow CRUD endpoints
- Project and trigger persistence endpoints
- User registry endpoints
- Run trigger and status endpoints
- Server-sent events stream for live run events
- Temporal client bridge
- Auth, RBAC, and secret boundary enforcement

## Persistence

- Postgres is the source of truth for users, projects, workflows, triggers, runs, and run events.
- Redis is used for hot cache and idempotency acceleration.
- Schema is defined in `apps/api/db/schema.sql` and applied automatically when `SCHEMA_AUTO_MIGRATE=true`.
