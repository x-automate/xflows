# Platform Audit — Nodes, Connections, Dashboard & Logs

A full pass over the node catalog, the canvas connection model, and the
dashboard/logs surfaces. Every claim below was checked against running code,
not read off the catalog: the node table comes from dispatching all 39
components through `create_default_registry()`, and the run behaviour comes
from real runs against a live API (`PERSISTENCE_MODE=memory`, Temporal absent,
so the local-fallback engine path).

Defects marked **[fixed]** were fixed in the same change as this document.
Defects marked **[open]** are described with a proposed fix but not yet done.

## 1. Baseline

| Suite | Result |
|---|---|
| `packages/xflows-engine/tests` | 155 passed |
| `apps/api/tests` | 38 passed, 1 skipped |
| `apps/workers/tests` | 140 passed |
| `apps/web` vitest | 29 passed |
| `ruff check apps packages tools` | clean |
| `eslint .` / `vite build` | clean |

## 2. Nodes

All 39 catalog components were dispatched through the engine with their
declared default params (plus minimal fixtures for executors with hard-required
params such as `XWSS3.key`). Result: **every component the editor lets you place
executes.** Nothing placeable is inert.

The catalog's `status` field gates placement — `isPlaceable()` refuses
`planned` — and it lines up with reality in every case:

| Category | Node | id | Status | Executor |
|---|---|---|---|---|
| Agent | Agent Loop | `AgentLoop` | working | `AgentLoopExecutor` |
| Agent | ReAct | `ReActAgent` | planned | `ChatLikeExecutor` (single turn only) |
| Control | Approval | `Approval` | working | `ApprovalExecutor` |
| Control | Codegen | `Codegen` | working | `CodegenExecutor` |
| Control | Loop Over Items | `LoopOverItems` | planned | none |
| Control | Schema Validate | `SchemaValidate` | working | `SchemaValidateExecutor` |
| Control | Sub Workflow | `SubWorkflow` | working | `SubWorkflowExecutor` |
| Control | Wait | `Wait` | working | `WaitExecutor` |
| Format | Markdown | `Markdown` | planned | none |
| I/O | Input | `Input` | working | `InputExecutor` |
| I/O | Output | `Output` | working | `OutputExecutor` |
| LLM | LLM | `LLM` | working | `ChatLikeExecutor` |
| LLM-Provider | OpenAI | `OpenAIChat` | working | `ChatLikeExecutor` |
| LLM-Provider | Claude | `AnthropicChat` | working | `ChatLikeExecutor` |
| LLM-Provider | LiteLLM | `LiteLLM` | working | `LiteLlmExecutor` |
| Memory | Vector DB | `VectorStore` | working | `VectorStoreExecutor` |
| Memory | Summarize | `Summarizer` | planned | none |
| Observability | Langfuse | `LangfuseTracer` | partial | `LangfuseTracerExecutor` |
| Observability | LangSmith | `LangsmithTracer` | planned | `LangsmithTracerExecutor` |
| Observability | Tracer | `Tracer` | planned | none |
| Observability | Guardrail | `Guardrail` | planned | none |
| Parser | JSON | `JsonParser` | planned | none |
| Parser | Regex | `RegexExtract` | planned | none |
| Prompt | Prompt | `PromptTemplate` | working | `PromptTemplateExecutor` |
| Router | If/Else | `IfElse` | working | `IfElseExecutor` |
| Router | Switch | `Switch` | working | `SwitchExecutor` |
| Tool | HTTP | `HttpRequest` | partial | `HttpRequestExecutor` |
| Tool | API Caller | `ApiCaller` | working | `ApiCallerExecutor` |
| Tool | Search | `WebSearch` | working | `WebSearchExecutor` |
| Tool | Code | `CodeExec` | planned | none |
| Trigger | Webhook | `Webhook` | planned | `WebhookTriggerExecutor` |
| XWS | XWS S3 | `XWSS3` | working | `XWS3Executor` |
| XWS | XWS Lambda | `XWSLambdaInvoke` | working | `XWSLambdaInvokeExecutor` |
| XWS | XWS IAM | `XWSIAMEvaluate` | working | `XWSIAMEvaluateExecutor` |
| XWS | XWS Relay | `XWSRelayNotify` | working | `XWSRelayNotifyExecutor` |
| XWS | XWS Gateway LLM | `XWSGatewayLLM` | working | `XWSGatewayLLMExecutor` |
| XWS | XWS DMS | `XWSDmsIntrospect` | planned | registered, raises `NotImplementedError` |
| XWS | XWS API GW | `XWSApigwRegister` | planned | registered, raises `NotImplementedError` |
| XWS | XWS Audit | `XWSAudit` | planned | registered, raises `NotImplementedError` |

Eight `planned` components have no executor at all and hit
`LoudFailureExecutor`, which is the intended design (XF-02: inert components
fail loudly rather than silently passing input through). Since the panel also
refuses to place them, that path is only reachable via an imported
`workflow.json`.

### Node findings

- **[fixed] `LangfuseTracer` declared no `icon`** and rendered an empty icon
  box on the canvas and in the component panel. Added `"icon": "trace"`, plus a
  catalog test asserting every component's icon resolves in `XFLOWS_ICONS`.
- **[open] There is no `Trigger` node you can place.** `Webhook` is the only
  `Trigger`-category component and it is `planned`, so a flow cannot express
  "start from an event" on the canvas at all. If a trigger node is wanted in the
  editor, it needs a catalog entry plus an ingestion endpoint (tracked as XU-8);
  today triggers live only in the separate Trigger tab.
- **[open] Six `planned` components do have working executors**
  (`Webhook`, `ReActAgent`, `LangsmithTracer`, `XWSDmsIntrospect`,
  `XWSApigwRegister`, `XWSAudit`). For the last three that is correct — they
  raise `NotImplementedError`. For `ReActAgent` and `LangsmithTracer` the
  `statusNote` says the executor is deliberately a reduced stand-in, so
  `planned` is a product call, not a bug. Worth revisiting whether "planned"
  should be split into "not built" and "built but reduced", since today both
  are unplaceable.

## 3. Connections and edges

### The red dashed edge

This was the reported symptom (an `LLM → Output` wire rendering red and dashed
instead of a normal black one). It is an **error edge** — `kind: "error"`, the
branch taken when a node throws — created by accident. Three causes, all fixed:

1. **[fixed] The error port was 1px from the data port.**
   `.wf-port-error-out` sat at `top: calc(50% + 11px)`; both ports are 10px
   across, so the data port spanned `50%±5px` and the error port started at
   `50%+6px`. Grabbing the wrong one was near-unavoidable. Moved to `+20px`.
2. **[fixed] Hover gave no feedback about which port you had.**
   `.wf-port:hover` painted *every* port the same blue, overriding the error
   port's red border at exactly the moment you needed it. The error port now
   hovers red and the config ports orange, and the data port has a tooltip
   (only the error port had one).
3. **[fixed] Wire endpoints did not land on their ports.** `errorOutPortPos()`
   used a `+16px` vertical offset against CSS's `+11px`, and the data/config
   endpoints were computed from the node box while the dots render 1px outside
   it. Both now derive from shared `PORT_CENTER` / `ERROR_PORT_DROP` constants.

### Connections were never gated

`connect()` accepted **any** source/target pair. The graph was only judged
afterwards, by `validateWorkflow`, as a line of text in the Validation tab. So
the canvas would happily draw:

| Connection | Was | Now |
|---|---|---|
| anything → `Input` | drawn, flagged later | refused, reason flashed |
| `Output` → anything | drawn, flagged later | refused |
| `LangfuseTracer` → `Output` (data) | drawn, never flagged | refused |
| `VectorStore` → `LLM.tracer` slot | drawn, flagged later | refused |
| config edge to a non-existent slot | drawn, flagged later | refused |
| an edge closing a cycle | drawn, whole graph invalid | refused |
| a nested provider wired directly | drawn, never flagged | refused |
| duplicate of an existing edge | silently ignored | refused with a reason |

`checkConnection()` in
`apps/web/src/features/workflow/catalog/connection-rules.js` is now the single
gate the canvas asks before an edge exists, and the refusal reason is shown as
a toast. 14 tests cover it. `validateWorkflow` is unchanged and still catches
graphs loaded from JSON.

### Config edges are decorative at run time **[open]**

The `TRACER` / `MEMORY` / `TOOLS` slots under the LLM container accept wires,
and the editor now validates them — but `normalize_workflow_graph()` drops
every `kind: "config"` edge before execution (`graph.py`, asserted by
`test_engine.py` and `test_control_flow.py`). So attaching Langfuse or a vector
store to an LLM container has **no effect on a run**. Tracing works, but only
through worker environment config, which is why `LangfuseTracer` is `partial`.

This is deliberate today, not a regression. But the UI gives no hint, and a
user wiring up those ports will reasonably expect them to do something. Either
consume config edges in the engine, or mark the slots as not-yet-wired in the UI.

### Error branches receive an empty value **[open]**

Verified with a live run. On an error edge the engine delivers:

```json
{"value": "", "error": {"message": "...", "nodeId": "gate", "componentId": "IfElse"}}
```

The `value` is deliberately blank, and `PromptTemplate` only substitutes
`{input}` — so a recovery branch renders `"FALLBACK for: "` with nothing after
it. The error detail is in the payload but unreachable from any node param.
Recovery branches need either `{error}` / `{error.message}` substitution or an
`Input`-like node that reads the error payload.

## 4. Dashboard

`pages/Dashboard.jsx` works — it lists projects from the API with a localStorage
fallback and creates new ones — but it is a project picker, not a dashboard. Its
three "stat cards" are hardcoded strings (`Environment: Development`,
`API Endpoint`, `Current Focus: Web shell and live backend status integration`).
No run counts, no success rate, no recent activity, no health.

The data mostly exists: `GET /projects`, `GET /projects/{id}/runs`, `GET /health`
and `GET /metrics`. What is missing is a **cross-project runs endpoint** — run
listing is per-project only, so "last 20 runs across all projects" is an N+1 of
project calls today. See the redesign proposal for the suggested shape.

## 5. Logs

`pages/ProjectLogs.jsx` works: it lists runs, expands a row into full event
history from `GET /runs/{id}/events/history`, and links to Run and View. The
defects are in what reaches it.

### Four of ten event types never reached the browser **[fixed]**

The API sends every run event as a **named** SSE frame (`event: node_skipped`),
confirmed on the wire:

```
id: 20
event: node_skipped
```

`EventSource.onmessage` does not fire for named events, so each type must be
subscribed by name — and `streamRunEvents` subscribed to 6 of the 10 in
`RunEvent.type`. Dropped on the floor: `node_skipped`, `node_routed_to_error`,
`run_awaiting_review`, `signal_received`.

The consequences were invisible rather than loud. `normalizeEvent` already
handled `node_skipped` and `node_routed_to_error`, and `workflow.css` already
had `.wf-node.run-skipped` and `.wf-node.run-routed` styles — they simply never
fired. **Any branching workflow ran with no feedback**: the untaken branch just
sat there looking un-executed, and a node that failed into its error branch
looked identical to one that never ran.

Fixed by subscribing to all ten, rendering skipped / routed / awaiting / signal
rows in the Test trace, adding a `skipped` node badge and an `awaiting` node
state, and pinning the client list to the API enum with a test that parses
`models.py` — so adding an event type server-side now fails the web suite until
the client handles it.

### The published event schema rejected real events **[fixed]**

The same enum is written out in four places, and all four had drifted apart:

| Declaration | Types |
|---|---|
| `apps/api/app/models.py` (what the API emits) | 10 |
| `packages/workflow-spec/run-events.schema.json` | 8 |
| `packages/workflow-spec/src/types.ts` | 6 |
| web `streamRunEvents` subscriptions | 6 |

So a genuine `node_skipped` event **failed validation against its own published
schema**, even though `run-events.md` calls that schema "the single source of
truth for both producers and consumers". Verified directly:

```
node_skipped FAILS schema validation:
'node_skipped' is not one of ['run_started', ..., 'run_failed']
```

All four now agree, and `apps/api/tests/test_run_event_contract.py` pins the
first three to `models.py` (including validating one event of every type
against the schema) while `workflowApi.test.js` pins the fourth.

### Run history still shows the expanded view only **[open]**

The `node_skipped` and `node_routed_to_error` events are emitted in
`execute_local_run` *after* the run completes, in a trailing loop over
`statuses`. Two consequences:

- They appear at the **end** of the event history, after the `node_succeeded`
  of nodes downstream of them — so the Logs detail table shows them out of
  causal order. Confirmed in a live run.
- On the **failure** path `runner.run()` raises, so `statuses` is never
  returned and these events are **never emitted at all**. A run that fails
  after skipping a branch loses the skip record entirely.

Fixing this properly means having `NodeGraphRunner` report per-node status as
it goes rather than only in its return value.

### Approvals have no UI at all **[open]**

`Approval` is a `working` node and freely placeable. When a run parks on it the
API emits `run_awaiting_review` and exposes
`POST /runs/{id}/approve`, `/reject` and `/request-changes`. **No screen in
`apps/web` calls any of them** (verified by grep). A workflow with an Approval
node parks until its `signalTimeoutS` expires with no way for a human to act
from the product. The canvas now at least *shows* the awaiting state; the
action buttons still need building.

## 6. Other defects found

- **[fixed] An empty graph failed with `list index out of range`.**
  `resolve_output_node_id()` did `order[-1]` on an empty list. A brand-new
  project whose flow has not been drawn yet is exactly this case. Now raises
  `Workflow has no nodes to execute; add an Input and an Output node`, verified
  end to end.
- **[fixed] Delete/Backspace did nothing on the three starter edges.**
  `deleteSelected()` identified edges with `selected.startsWith("e_")`, but
  `STARTER()` creates `e1`/`e2`/`e3`. The keypress fell through to the node
  branch and removed nothing, silently. Now looks the edge up by id.
- **[fixed] The Configs page reported success on failure.** `setSaved(true)`
  ran in the `catch`, so a failed API sync showed both "Configs saved for this
  project." and the error. It now says the values were saved locally only and
  will not reach the worker.
- **[fixed] Node search matched the display name only** — searching `trace`,
  `xws` or a component id returned nothing. Now matches name, id, category and
  description.

## 7. Open items, by cost

| Item | Where | Rough size |
|---|---|---|
| Approval UI (approve / reject / request changes) | `apps/web` + existing endpoints | small — endpoints exist |
| Per-node status emitted during the run, not after | `packages/xflows-engine/graph.py` | medium — runner signature |
| Error payload reachable from node params (`{error}`) | engine + `PromptTemplate` | small |
| Config edges consumed by the engine, or marked inert in the UI | `graph.py` or `Canvas.jsx` | medium / trivial |
| Cross-project runs endpoint for a real dashboard | `apps/api` | small |
| A placeable Trigger node | catalog + ingestion endpoint (XU-8) | large |
