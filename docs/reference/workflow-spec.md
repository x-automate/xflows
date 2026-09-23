# Workflow Spec Package

`packages/workflow-spec` is the shared contract between frontend, API, and workers: JSON
Schemas, TypeScript types, versioning rules, and a canonical example.

## Package Layout

```
packages/workflow-spec/
├── workflow.schema.json      # Workflow document schema (draft 2020-12)
├── run-events.schema.json    # Run event schema (draft 2020-12)
├── versioning.md             # Lifecycle + compatibility rules
├── examples/basic-workflow.json
├── src/types.ts              # TS contract types (package export)
├── package.json              # @xflows/workflow-spec v0.1.0, private, no deps/build
└── README.md
```

## Workflow Schema (`workflow.schema.json`)

- `$id`: `https://xflows.dev/schemas/workflow.schema.json`
- Required: `id`, `name`, `version`, `status`, `nodes`, `edges`, `createdAt`, `updatedAt`
- `id`: `^[a-zA-Z0-9_-]{3,64}$`; `name`: 1–120 chars; `description`: optional ≤2000
- `version`: integer ≥ 1; `status`: `draft | published | archived`
- `nodes`: minItems 1; each node requires `id`, `componentId`, `x`, `y`, `params`
  (`additionalProperties: false` — so `parent` from the API model is outside the schema today)
- `edges`: each requires `id`, `source`, `target` (no `kind`/`slot` in the schema yet)
- `metadata`: free object; `createdAt`/`updatedAt`: date-time

The worker/API models (`WorkflowNode`, `WorkflowEdge`, `WorkflowDefinition`) are a superset of
this schema: they add `parent` (nested provider children) and edge `kind`/`slot`. Keep schema and
models in sync when evolving shapes (see [versioning rules](../../packages/workflow-spec/versioning.md)).

## Run Events Schema (`run-events.schema.json`)

- Required: `runId`, `type`, `timestamp`; `additionalProperties: false`
- `type` enum: `run_started`, `node_started`, `node_succeeded`, `node_failed`, `run_succeeded`,
  `run_failed`
- Optional: `nodeId`, `payload`, `traceId`

Details and transport semantics: [Run events reference](run-events.md).

## TypeScript Types (`src/types.ts`)

```ts
type WorkflowStatus = "draft" | "published" | "archived";
interface WorkflowNode  { id; componentId; x; y; params }
interface WorkflowEdge  { id; source; target }
interface WorkflowDefinition { id; name; description?; version; status;
                               nodes; edges; metadata?; createdAt; updatedAt }
interface RunRequest    { input; idempotencyKey?; metadata? }
interface RunRecord     { id; workflowId; workflowVersion; status; input; output?; error?;
                          startedAt?; finishedAt?; traceId? }
interface RunEvent      { runId; type; nodeId?; payload?; timestamp; traceId? }
```

(`RunRecord.status`: `queued | running | succeeded | failed | cancelled`.)

## Example Workflow (`examples/basic-workflow.json`)

Canonical four-node flow used by the eval harness (`WORKFLOW_ID = wf_support_assistant`):

```
Input → PromptTemplate → OpenAIChat → Output
```

params: template `Answer clearly and concisely:\n\n{input}`, system `You are a helpful assistant.`,
model `gpt-4o-mini`, temperature 0.3, max_tokens 256; status `published`, version 1, metadata
tags `["assistant", "starter"]`.

## Versioning Rules

From `versioning.md` — the target lifecycle (status values exist in the contract; the
publish/archive endpoints are not implemented yet, see
[data model](data-model.md#workflows)):

- `draft`: editable and testable. New workflows start at `version=1`.
- `published`: immutable executable version for production runs; publishing clones the draft into
  an immutable published version and increments the draft's version number.
- `archived`: non-executable, retained for audit/replay.
- Runs bind to `workflowId + version`; existing runs are never affected by later edits; replays
  always use original version semantics.
- **Compatibility**: additive node-param changes are backward compatible; removing node ids,
  changing component semantics, or edge behavior requires a new published version. Workers should
  use feature flags to preserve deterministic replay for old versions.

## Usage in the Codebase

| Consumer | How it uses the spec |
|---|---|
| `apps/web` | node/edge JSON shape (editor graph, JSON export/import); run request types |
| `apps/api` | Pydantic models mirroring the schema; event literal types |
| `apps/workers` | `WorkflowDefinition` validation at the Temporal entrypoint |
| `tools/evals` | the example workflow id + run contract |
