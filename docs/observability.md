# Observability

Three layers: **metrics** (Prometheus), **tracing** (Langfuse), and **run events** (SSE / event
history). Related docs: [architecture/observability-evaluation](architecture/observability-evaluation.md)
(goals & SLO design), [deployment](deployment/docker-compose.md) (scrape config), and the
alert file `deploy/docker/prometheus-alerts.yml`.

## Metrics

### API (`GET /metrics`, port 8000)

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `xflows_runs_created_total` | Counter | — | Runs created |
| `xflows_runs_completed_total` | Counter | `status` | Terminal runs by status |
| `xflows_run_create_latency_seconds` | Histogram | — | Run-create endpoint latency |

### Worker (Prometheus HTTP server, port 9464)

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `xflows_node_executions_total` | Counter | `component`, `status` (`success`/`error`) | Node activity outcomes |
| `xflows_node_execution_seconds` | Histogram | `component` | Node activity duration |

Prometheus scrapes both (jobs `xflows-api`, `xflows-worker`, 15 s interval).

### Alert Rules

| Alert | Trigger | Severity |
|---|---|---|
| `XFlowsApiDown` | API scrape down 2m | critical |
| `XFlowsWorkerDown` | Worker scrape down 2m | critical |
| `XFlowsRunCreateLatencyHigh` | P95 run-create latency > 2s over 5m, sustained 10m | warning |
| `XFlowsNodeErrorRateHigh` | Node error rate > 5% over 10m | warning |

### SLOs (suggested, from the architecture doc)

- Run-create availability ≥ 99.9%
- P95 run creation ≤ 2 s
- Node execution error rate ≤ 5%
- End-to-end run success ≥ 95% (excluding input-validation failures)

## Tracing (Langfuse)

Implemented in `apps/workers/app/tracing.py`:

- The `LangfuseTracer` initializes a real client **only when** `LANGFUSE_HOST`,
  `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` are all set; otherwise it degrades to no-op
  spans (no crashes, no external calls).
- **Trace model**: one trace per run (trace id = the run's `traceId`), one span per node
  execution named `node:{componentId}`, metadata `{runId}`, input = the node's input payload.
- On success the span level is DEFAULT; on exception the span is marked ERROR with the error as
  `status_message`.
- Every activity flushes its span in a `finally` block.
- Tracer *nodes* (`LangfuseTracer`/`LangsmithTracer`) in a workflow don't create spans
  themselves; they attach config metadata to the run (see
  [node execution](reference/node-execution.md#built-in-executors)). Configure the actual
  backend via worker env (self-hosted Langfuse at `localhost:3001` when the observability
  profile runs, or Langfuse cloud).

Where to look:

- **Langfuse UI** (`http://localhost:3001`, project `xflows` seeded by compose): prompt/response,
  metadata, and error levels per node.
- **Temporal UI** (`http://localhost:8081`): workflow histories, retry counts, activity failures —
  search by the Temporal id `{workflowId}:{runId}`.

## Run Events as Observability Data

The event stream is itself an audit log: `GET /runs/{runId}/events/history` gives the full
ordered event log per run (also rendered in the Logs tab "Details" expander). Event ids are
monotonic, so event history doubles as the replay/cursor source. See
[run events reference](reference/run-events.md).

## Regression Evaluation

`tools/evals/` — golden-set regression harness (see
[development guide](guides/development.md#evaluation-harness) for usage):

- Cases: `tools/evals/testcases.json` — `{name, input, expect_contains_any}` (case-insensitive
  substring match on run output; empty array = status-only).
- Runner: `tools/evals/regression_eval.py` POSTs to
  `POST /workflows/wf_support_assistant/runs`, polls to terminal status (90 s cap, 0.5 s cadence),
  and reports `{total, failures, p95_latency_seconds}`; exit 1 on any failure.
- Release gates (suggested in the architecture doc): success ratio, max failures, latency
  percentile thresholds.
