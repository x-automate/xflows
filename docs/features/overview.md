# Feature Map & User Journeys

This page maps every user-facing feature of XFlows and links to its deep-dive page.

## Feature Matrix

| Area | Feature | Where | Deep dive |
|---|---|---|---|
| **Dashboard** | Create projects, list projects (remote-first with localStorage fallback), API endpoint info cards | `apps/web/src/pages/Dashboard.jsx` | [Projects](projects-configs-triggers.md#dashboard) |
| **Status** | Backend health polling (`GET /health` every 10s, Temporal connectivity shown) | `apps/web/src/pages/Status.jsx` | [Projects](projects-configs-triggers.md#status-page) |
| **Editor** | Drag-and-drop canvas: pan/zoom, data edges, config slots, containers, provider chips | `apps/web/src/features/workflow/components/Canvas.jsx` | [Workflow editor](workflow-editor.md) |
| | Component palette: searchable, grouped by category, draggable + double-click add | `components/ComponentPanel.jsx` | [Editor](workflow-editor.md#component-panel) |
| | Node params: inline Properties panel + ParamModal form (select/number/text/textarea/bool) | `components/PropertiesPanel.jsx`, `ParamModal.jsx` | [Editor](workflow-editor.md#parameter-editing) |
| | Steps pane: Properties / Steps / Test / Validation tabs | `components/StepsPane.jsx` | [Editor](workflow-editor.md#steps-pane) |
| | Validation: acyclic, one Input/Output, port rules, provider containment, slot compatibility | `hooks/useWorkflowValidation.js` | [Editor](workflow-editor.md#validation) |
| | Undo/redo + keyboard shortcuts + duplicate/delete + clear all + JSON export/import | `features/workflow/AppShell.jsx` | [Editor](workflow-editor.md#history-and-shortcuts), [import/export](workflow-editor.md#json-importexport) |
| **Node catalog** | 42 components across 14 categories, driven by `node-registry.json` (params, defaults, config slots, project configs) | `packages/xflows-catalog/node-registry.json` | [Node catalog](node-catalog.md) |
| **Configs** | Dynamic credential/config form derived from nodes in the flow; saved as project `configs`; passed to runs as `metadata.runtimeConfig` | `src/pages/ProjectConfigs.jsx` | [Projects & configs](projects-configs-triggers.md#configs-tab) |
| **Triggers** | Time-based trigger table (enabled, queue, time, timezone); syncs to `POST/PATCH /projects/:id/triggers` | `src/pages/ProjectTriggers.jsx` | [Triggers](projects-configs-triggers.md#trigger-tab) |
| **Runs** | Editor Test tab: start run, live trace log, per-node durations, final output | `AppShell.jsx` (TestPanel) | [Runs](runs.md#test-runs-from-the-editor) |
| | Project run page: run input form, run summary, link to live view | `src/pages/ProjectRun.jsx` | [Runs](runs.md#project-run-page) |
| | Run history (Logs tab): status badges, expandable event history per run | `src/pages/ProjectLogs.jsx` | [Runs](runs.md#run-history-logs) |
| | Live view: read-only canvas replaying a real run over SSE, or scripted demo playback | `src/pages/ProjectView.jsx` | [Runs](runs.md#live-view) |
| | SSE streaming with `Last-Event-ID` resume + 1.2s status polling as belt-and-braces | `lib/api/workflowApi.js` | [Run events](../reference/run-events.md) |
| **Backend** | Workflow CRUD + project-scoped run orchestration, idempotency, triggers, users | `apps/api/app/main.py` | [API reference](../reference/api-reference.md) |
| | Durable execution with per-node retries/timeouts, local fallback execution | `apps/workers`, `apps/api` | [Node execution](../reference/node-execution.md) |
| | Model routing via LiteLLM with fallback chain | `apps/workers/app/provider_router.py` | [Node execution](../reference/node-execution.md#model-routing-fallback-chain) |
| | Prometheus metrics + alert rules | API `/metrics`, worker :9464 | [Observability](../observability.md) |
| | Langfuse tracing per run/node | `apps/workers/app/tracing.py` | [Observability](../observability.md#tracing-langfuse) |

## Routes

Defined in `apps/web/src/App.jsx` (react-router v6):

| Route | View | Notes |
|---|---|---|
| `/` | → `/dashboard` | Redirect |
| `/dashboard` | Dashboard | Project list + creation |
| `/editor` | WorkflowEditor | Standalone editor (no project scope) |
| `/status` | Status | Health polling |
| `/project/:projectId` | ProjectLayout | Tab nav (Flow / Configs / Trigger / Logs), project via outlet context |
| `  /flow` | WorkflowEditor | Project-scoped editor (default tab) |
| `  /configs` | ProjectConfigs | Credentials & global params |
| `  /trigger` | ProjectTriggers | Trigger table |
| `  /logs` | ProjectLogs | Run history |
| `  /run/new` → `/run/:runId` | ProjectRun | Start + monitor a run (`run/new` allowed) |
| `  /view/:runId` | ProjectView | Live read-only run visualization |
| `  /run`, `/view` | → `/logs` | Redirects |
| `/flows`, `/triggers` | → `/dashboard`, `/project/:id/trigger` | Legacy aliases |

## User Journeys

### Journey 1: Build and test a workflow

1. Dashboard → create project → land on Flow tab.
2. Drag nodes, connect data edges, drop a provider into the LLM container.
3. Fix validation errors flagged in the Validation tab until the workflow is valid.
4. Configs tab → fill required credentials (derived from the flow's nodes).
5. Test tab → run → watch the trace, inspect durations and outputs.

### Journey 2: Operate a workflow

1. Logs tab → find historical runs, status badges, deep links.
2. `Run` → `/run/{runId}` to re-execute or review; `View` → `/view/{runId}` to watch the live
   canvas of that run (SSE replay).
3. Trigger tab → manage scheduled triggers; executions appear in Logs.
4. Temporal UI / Langfuse / Grafana for deep diagnostics.

## Offline-First Data Model

The frontend keeps a localStorage project store (`xflows_projects`) as the fast path and
fallback:

- Graph edits: instant local write, then 500ms-debounced `PATCH /projects/:id`.
- Project lists/runs/triggers: API first, localStorage on failure.
- A project that exists locally but not remotely is auto-created on first load of its workspace
  (`ProjectLayout.jsx`).
- Run results are also mirrored locally (`addProjectRun` / `updateProjectRun`), so history
  survives backend restarts in the UI.

This is a UX safety net, not a source of truth — Postgres remains authoritative (see
[Data model](../reference/data-model.md)).
