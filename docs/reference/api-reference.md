# REST API Reference

Base URL: `http://localhost:8000` (service `api`; all field names are camelCase, JSON bodies).
All routes are defined in `apps/api/app/main.py`; Pydantic models in `apps/api/app/models.py`.

- No user-facing auth today. The only protected route is the internal worker callback
  (`x-internal-token` header checked against `INTERNAL_API_TOKEN`; unset = check disabled).
- CORS: configurable origins (`CORS_ORIGINS`, default `http://localhost:4173`,
  `http://127.0.0.1:4173`), credentials enabled, all methods/headers.
- Errors use `HTTPException` with a `detail` string: 404 missing resource, 409 duplicate
  workflow id, 401 invalid internal token.

## Health

### `GET /health`

```json
{ "status": "ok", "temporal": "connected" }
```

`temporal` is `"connected"` or `"disconnected: <reason>"`. Probes Temporal connectivity
(lazily connects and caches the client).

## Users

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/users` | `{email, name, authProvider?}` (`authProvider` defaults `"local"`) | Creates a user (id: uuid4) |
| GET | `/users` | — | List, newest first |
| GET | `/users/{user_id}` | — | 404 if missing |

## Projects

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/projects` | `{id?, name, description?}` | Server defaults: `graph={"nodes":[],"edges":[]}`, `configs` defaults |
| GET | `/projects` | — | List, ordered by `updatedAt` desc |
| GET | `/projects/{project_id}` | — | 404 if missing |
| PATCH | `/projects/{project_id}` | any of `{name, description, graph, configs, metadata, lastRun}` | Partial update via `exclude_unset` merge |

`ProjectRecord`:

```json
{
  "id": "…", "ownerUserId": null, "name": "…", "description": null,
  "graph": { "nodes": [], "edges": [] },
  "configs": { "hasOpenAIKey": false, "model": "gpt-4o-mini",
               "temperature": 0.7, "maxTokens": 512 },
  "metadata": {}, "lastRun": null,
  "createdAt": "…", "updatedAt": "…"
}
```

Default `configs` come from `DEFAULT_CONFIGS` in `apps/api/app/store.py`.

## Triggers

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/projects/{project_id}/triggers` | — | 404 if project missing |
| POST | `/projects/{project_id}/triggers` | `{type, enabled?, config?}` | `type`: `"time" \| "webhook" \| "event"`; id `trg_<10 hex>` |
| PATCH | `/projects/{project_id}/triggers/{trigger_id}` | `{enabled?, config?}` | 404 if trigger missing |

Example create body:

```json
{ "type": "time", "enabled": true,
  "config": { "queue": "support", "time": "09:00", "timezone": "Local" } }
```

## Workflows

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/workflows` | see below | 409 if id already exists |
| GET | `/workflows` | — | List, `createdAt` desc |

Create body (`WorkflowCreateRequest`):

```json
{
  "id": "wf_support_assistant",
  "name": "Support Assistant",
  "description": "…",
  "nodes": [ { "id": "node_input", "componentId": "Input", "x": 0, "y": 0, "params": {} } ],
  "edges": [ { "id": "edge_1", "source": "node_input", "target": "node_prompt" } ],
  "metadata": { "projectId": "…", "tags": [] }
}
```

- Node: `{id, componentId, x?, y?, parent?, params?}` — `parent` marks a nested provider child
  (promoted into its container at execution; see
  [node execution](node-execution.md#graph-normalization)).
- Edge: `{id, source, target, kind?, slot?}` — `kind: "data"` is the executable type; `"config"`
  edges are designer metadata only.
- `WorkflowRecord` adds `version` (starts at 1), `status` (`draft`), `createdAt`, `updatedAt`.
- There is no GET-by-id, PATCH, or DELETE for workflows over HTTP; project-run requests upsert
  the project workflow internally.

## Runs

### `POST /workflows/{workflow_id}/runs`

Body (`RunRequest`):

```json
{ "input": "What is XFlows?",
  "idempotencyKey": "optional-key",
  "metadata": { "runtimeConfig": { "litellmModel": "gpt-4o-mini",
                                   "litellmApiKey": "sk-…",
                                   "litellmBaseUrl": "http://localhost:4000" } } }
```

Response (`RunRecord`, returned immediately):

```json
{ "id": "run_ab12cd34ef56ab12", "projectId": null, "workflowId": "wf_support_assistant",
  "workflowVersion": 1, "status": "queued", "input": "…", "output": null, "error": null,
  "traceId": "trace_ab12cd34ef56ab12", "metadata": {}, "startedAt": null, "finishedAt": null }
```

Behavior:

- Run id `run_<16 hex>`; status `queued`; `RUNS_CREATED` counter increments.
- Idempotency: same `(workflowId, idempotencyKey)` within the TTL (default 24 h) returns the
  original run (Postgres advisory-locked; see [data model](data-model.md#idempotency)).
- Temporal start is fire-and-forget; if Temporal is unreachable the API runs the workflow locally
  in the background.

### `POST /projects/{project_id}/runs`

Body (`ProjectRunRequest`):

```json
{ "input": "ticket text…",
  "idempotencyKey": "…",
  "metadata": { "runtimeConfig": { } },
  "workflow": { "name": "…", "description": "…", "nodes": [ … ], "edges": [ … ], "metadata": {} } }
```

Behavior:

- `ensure_project` auto-creates the project if absent.
- Upserts the project's implicit workflow with id `wf_{project_id}` (metadata gains
  `projectId` + `source: "project_run"`; version is **not** bumped on overwrite).
- Then starts the run exactly like the workflow endpoint (with `projectId` recorded).

### `GET /projects/{project_id}/runs`

List runs for a project, ordered by `COALESCE(started_at, created_at)` desc. 404 if project
missing.

### `GET /runs/{run_id}`

Single run record. Poll this for terminal status; the web client does so every ~1.2 s during
runs.

### `GET /runs/{run_id}/events/history?after_id=N`

Up to 2000 `RunEvent`s, ascending by event id. `after_id` (query, int) is the cursor. 404 if
run missing. See [run events](run-events.md).

### `GET /runs/{run_id}/events` (SSE)

Server-Sent Events stream. Same semantics as history but live:

- Query `after_id` or the `Last-Event-ID` header set the resume cursor.
- Polls the store every 0.2 s, batching up to 200 events per tick.
- SSE frames: `id:` = event id, `event:` = event type, `data:` = full `RunEvent` JSON.
- Self-terminates after 300 consecutive idle ticks (~60 s of silence); reconnecting clients
  should send `Last-Event-ID` (the browser `EventSource` does this automatically).
- 404 if run missing.

### `POST /internal/runs/{run_id}/events` (internal)

Worker → API event ingestion.

- Header: `x-internal-token: <INTERNAL_API_TOKEN>` (401 if mismatched when configured).
- Body: `{type, nodeId?, payload?, traceId?}` where `type` is one of the six event types.
- Side-effects: `run_started` → run becomes `running` (sets `startedAt` once);
  `run_succeeded` → `succeeded` + `output` from `payload.output`;
  `run_failed` → `failed` + `error` from `payload.error`; both set `finishedAt`.

## Metrics

### `GET /metrics`

Prometheus text exposition. API-registered metrics:

| Metric | Type | Labels |
|---|---|---|
| `xflows_runs_created_total` | Counter | — |
| `xflows_runs_completed_total` | Counter | `status` |
| `xflows_run_create_latency_seconds` | Histogram | — |

Worker metrics (port 9464) are listed in [Observability](../observability.md#metrics).

## Error Semantics

| Status | When |
|---|---|
| 404 | Unknown user/project/trigger/workflow/run (+ detail naming the id) |
| 409 | `POST /workflows` with an existing id |
| 401 | Internal event endpoint with wrong/missing token (when token configured) |
| 422 | Pydantic validation errors (FastAPI default) |

Node-level execution errors (bad URL params, cycles, LiteLLM failures) are **not** HTTP errors —
they surface as `run_failed` events with the error string, keeping the run lifecycle intact.
