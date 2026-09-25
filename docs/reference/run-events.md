# Run Events

The run event contract is shared by the API, workers, SSE consumers, and the web client.
Canonical schema: `packages/workflow-spec/run-events.schema.json` (JSON Schema draft 2020-12);
Pydantic mirror in `apps/api/app/models.py` (`RunEvent`, `InternalRunEventRequest`).

## Event Types

| Type | Emitted by | Meaning | Typical payload |
|---|---|---|---|
| `run_started` | API (at creation) / worker | Run accepted / started | `{}` |
| `node_started` | API fallback / worker | Node execution begins | `{}` |
| `node_succeeded` | API fallback / worker | Node finished | `{output: <value>, metadata: {...}}` |
| `node_failed` | API fallback / worker | Node raised | `{error: "…"}` |
| `run_awaiting_review` | worker (`xflows.prepare_approval`, XU-5) | Approval gate parked the run; run status becomes `awaiting_review` | `{summary: "…", signalTimeoutS: 259200}` |
| `signal_received` | API (approval endpoints) / worker (`xflows.record_approval`) | A HITL decision was recorded | `{signal: "approved|rejected|request_changes|timeout", reviewer, comment, evidence}` |
| `run_succeeded` | API fallback / worker completion | Run finished successfully | `{output: "…"}` |
| `run_failed` | API fallback / worker completion | Run failed | `{error: "…"}` |

Run-state side effects for the new types (internal ingestion endpoint): `run_awaiting_review`
sets run status `awaiting_review`; `signal_received` maps `approved` → `running`,
`rejected` → terminal `rejected`, `timeout` → terminal `escalated` (04 §6 run state model).

`RunEvent` shape:

```json
{
  "id": 42,
  "runId": "run_ab12cd34ef56ab12",
  "type": "node_succeeded",
  "nodeId": "node_llm",
  "payload": { "output": "…", "metadata": { "provider": "openai", "model": "gpt-4o-mini" } },
  "timestamp": "2026-05-07T12:00:00.000000Z",
  "traceId": "trace_ab12cd34ef56ab12"
}
```

- `id`: monotonic BIGSERIAL id assigned by the store (Postgres) or an in-memory counter — this is
  the SSE cursor.
- `nodeId`: present for node events, null for run-level events.
- `traceId`: the run's trace id; the internal ingestion endpoint falls back to the run's stored
  trace id when omitted.

## Where Events Are Created

1. **API at run creation**: `run_started` appended when a run is created
   (`_create_run_impl` in `apps/api/app/main.py`).
2. **Worker during execution**: each node emits `node_started` before dispatch and
   `node_succeeded`/`node_failed` after; `xflows.complete_run` emits `run_succeeded` /
   `run_failed`. Events are POSTed to `POST /internal/runs/{runId}/events` with header
   `x-internal-token` (`publish_event` in `apps/workers/app/activities.py`).
3. **API local fallback**: `execute_local_run` emits the identical sequence directly into the
   store when Temporal is unavailable.
4. **API on ingestion**: the internal endpoint applies run-state side-effects (status, output,
   error, timestamps) for `run_started` / `run_awaiting_review` / `signal_received` /
   `run_succeeded` / `run_failed`.

Ordering: events are strictly append-only per run with monotonic ids — this enables SSE resume
cursors and deterministic replay (see [data model](data-model.md#tables)).

## SSE Protocol Details

`GET /runs/{runId}/events`:

- Framing: `id: <event id>` / `event: <type>` / `data: <RunEvent JSON>` per event.
- Cursor: query param `after_id` (int) or the `Last-Event-ID` header (header wins when numeric).
- Cadence: the server polls the store every 0.2 s and yields up to 200 events per tick.
- Idle shutdown: 300 consecutive idle ticks (~60 s) close the stream. Consumers should reconnect
  with `Last-Event-ID` (browser `EventSource` does this automatically).
- 404 if the run doesn't exist.

Client consumption (`apps/web/src/lib/api/workflowApi.js` → `streamRunEvents`) registers
listeners for the default channel **and every named type in `RUN_EVENT_TYPES`**; malformed
payloads are ignored; `onerror` closes; returns a cleanup function. The editor additionally
polls `GET /runs/{runId}` every 1.2 s until a terminal status as a safety net.

> Because the server always sets `event: <type>`, `EventSource.onmessage` never fires for run
> events — every type must be subscribed **by name**. A type missing from `RUN_EVENT_TYPES` is
> dropped silently, which is how `node_skipped` and `node_routed_to_error` went unrendered.
> `workflowApi.test.js` pins the list against `apps/api/app/models.py`.

## Schema Validation

Validate any event against the JSON Schema:

```bash
# packages/workflow-spec — draft 2020-12 schema
# required: runId, type, timestamp; additionalProperties: false
# type enum: run_started | node_started | node_succeeded | node_failed |
#            node_skipped | node_routed_to_error | run_awaiting_review |
#            signal_received | run_succeeded | run_failed
```

The enum is declared in four places — `apps/api/app/models.py`, this JSON Schema,
`packages/workflow-spec/src/types.ts` and the web client's `RUN_EVENT_TYPES`. They had drifted
to four different lengths (10 / 8 / 6 / 6), so a real `node_skipped` event failed validation
against its own published schema. `apps/api/tests/test_run_event_contract.py` now pins the
first three to each other and `workflowApi.test.js` pins the fourth; treat `models.py` as the
source and let the tests fail you if you change it alone.

Note: the worker's Pydantic/HTTP layer mirrors the same types, so the schema is the
single source of truth for both producers and consumers. TypeScript types live in
`packages/workflow-spec/src/types.ts`. The `run-events.schema.json` enum is updated in the
same change as the Pydantic literals — keep both in sync.
