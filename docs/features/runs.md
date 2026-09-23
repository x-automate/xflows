# Runs

Everything about executing workflows and observing execution.

## Run Lifecycle

Status flow on the `RunRecord`: `queued → running → awaiting_review? → succeeded | failed`,
plus the Wave 4 terminals `rejected` (reviewer rejected) and `escalated` (approval timed out);
`cancelled` exists in the contract for future use.

1. Client submits a run (editor Test tab or project run page).
2. API creates the run (`queued`), generates `trace_{uuid4hex16}`, emits `run_started`, and
   starts the Temporal workflow `XFlowsWorkflow.run` (id `{workflowId}:{runId}`) — or, when the
   stored workflow's metadata declares `{"apigen": "generate|validate|deploy"}`, the dedicated
   `ApiGen*Workflow.run` pipeline (see below).
3. On successful Temporal start the run becomes `running` immediately; otherwise the API falls
   back to local execution with the same engine and events — **unless the workflow is durable**
   (XU-9): durable workflows refuse the fallback and return **503** so pipeline runs are never
   fire-and-forget (fix XF-03).
4. The worker executes nodes one by one, emitting `node_started`/`node_succeeded`/`node_failed`
   events back to the API; `xflows.complete_run` emits the terminal event. An `Approval` node
   parks the run: `run_awaiting_review` sets status `awaiting_review`.
5. API applies terminal side-effects: sets `status`, `output` or `error`, `finishedAt`.

## APIGen Pipeline Runs (Wave 5)

Workflows whose metadata declares `{"apigen": "generate"}` (or `validate` / `deploy`) dispatch
to the durable pipeline workflows in `apps/workers/app/workflows.py`:

- `apigen.generate` — full pipeline: classify → clarify (≤5) → spec loop (≤5, linted) →
  codegen → validate child + ≤3 deterministic repair rounds → review gate → policy check →
  deploy child → manifest. Needs Temporal (durable); no local fallback.
- `apigen.validate` — bundle validation via the `apigen-bundle-validator` Lambda; input is a
  JSON string with `bundleHash` (or `bundle.hash`).
- `apigen.deploy` — deployment via the `apigen-deployer` Lambda; runtime `*Ref` entries
  become `secretBindings`; output includes the deploy manifest (`specHash`, aliases,
  `deployedAt`).

`SubWorkflow` nodes reference these pipelines by id (`workflowId: "apigen.validate"`), and
any other stored workflow id is resolved at run time through the `xflows.load_workflow`
activity, which fetches the definition from the internal-token-guarded
`GET /internal/workflows/{id}` API endpoint (XU-3).

## HITL Approvals (Wave 4, XU-5)

An `Approval` node parks the run on durable Temporal signals:

- `POST /runs/{id}/approve` — reviewer + optional comment; resumes the gate.
- `POST /runs/{id}/reject` — **comment is mandatory**; terminal `rejected` (artifacts retained).
- `POST /runs/{id}/request-changes` — feeds back into the clarifying loop (P1 in the pipeline).
- `signalTimeoutS` (node param, default 72h) — on expiry the decision is `timeout` → `escalated`.

Auth: reviewer or owner role (XU-7); unauthorized callers get 403, unknown tokens 401.
Every decision emits `signal_received` with reviewer/comment/evidence; before parking,
`run_awaiting_review` + a relay notification (card + deep link) are sent (05 §7).

Retry/timeout specifics: per-node schedule-to-close 120 s, up to 3 attempts with exponential
backoff (1 s → 20 s max). See [node execution reference](../reference/node-execution.md).

## Test Runs from the Editor

`AppShell.runWorkflow()` (Test tab in the Steps pane):

1. Validates the workflow; checks for unsupported components (`getUnsupportedComponents`).
2. Creates a workflow record via `POST /workflows` (id `wf_web_editor_<timestamp>`; a 409 is
   tolerated).
3. Calls `POST /workflows/{id}/runs` with the test input and
   `metadata.runtimeConfig = project.configs`.
4. Streams events over SSE and simultaneously polls `GET /runs/{runId}` every 1.2 s until the
   status leaves `queued`/`running` (belt-and-braces in case SSE drops).
5. Renders the trace: per-node start/success/error rows with durations, provider/model metadata,
   truncated outputs, and the final output.

If Temporal is unavailable, everything looks identical — the API's local fallback emits the same
events (that's the point of the shared node engine).

## Project Run Page

`/project/{id}/run/new` → `pages/ProjectRun.jsx`:

- Input form (seeded with a sample customer-support ticket).
- Starts the run via `POST /projects/{id}/runs` — payload includes the **workflow snapshot**
  (name, description, nodes, edges) plus `input` and `metadata.runtimeConfig`.
- The API upserts the project's implicit workflow (`wf_{projectId}`) and starts the run.
- The client mirrors the run locally, patches `lastRun` to the project, and navigates to
  `/project/{id}/run/{runId}` showing a run summary with a link to the live view.

## Run History (Logs)

`/project/{id}/logs` → `pages/ProjectLogs.jsx`:

- Table of runs: Run ID, status badge, started time, and actions. Badge tone mapping
  (`toneFor` in the page): `succeeded` → healthy, `running`/`queued` → degraded, anything else →
  error.
- Actions: **Run** → `/run/{runId}`, **View** → `/view/{runId}` (live view).
- **Details** expander lazily fetches `GET /runs/{runId}/events/history` and renders the event
  log (time, type, nodeId, JSON payload).
- "Start new run" → `/run/new`.
- Merges the remote run list with the local mirror, so history remains visible even across
  backend restarts.

## Live View

`/project/{id}/view/{runId}` → `pages/ProjectView.jsx`:

- Read-only editor shell bound to a `liveRunId`, showing a "LIVE" banner while replaying the
  real run's SSE stream.
- Without a run id (`autoReplay`), plays a scripted demo execution (timers per topological node,
  ~750 ms apart) for showcase purposes.

## Event Streaming (SSE)

`GET /runs/{runId}/events` — full protocol in [Run events reference](../reference/run-events.md);
client side in `lib/api/workflowApi.js` (`streamRunEvents`):

- Listens to the default channel plus named events: `run_started`, `node_started`,
  `node_succeeded`, `node_failed`, `run_succeeded`, `run_failed`.
- Malformed events are ignored; `onerror` closes the stream; the client returns a cleanup
  function.
- Resume: the server honors `Last-Event-ID`; the server-side stream idles out after ~60 s of
  silence, so the client's polling loop is the safety net.
- Event normalization in the editor: `node_started → start`,
  `node_succeeded → success {duration, output, metadata}`, `node_failed → error`.

## Trace Identifiers

- `traceId` is created by the API at run creation, stored on the run and every event, and used
  as the Langfuse trace id — one trace per run, one span per node (`node:{componentId}`).
- See [Observability](../observability.md#tracing-langfuse) and
  [architecture observability](../architecture/observability-evaluation.md).
