# XFlows

XFlows is evolving from a browser-only proof of concept into a production-grade
agentic workflow platform.

## Repository Layout

- `apps/web`: Frontend application (React UI and workflow authoring surface)
- `apps/api`: FastAPI gateway for workflow CRUD, run management, and run streams
- `apps/workers`: Temporal workers and activity executors
- `packages/workflow-spec`: Shared workflow schema, versioning rules, and examples
- `deploy/docker`: Docker Compose deployment assets for single-VM runtime
- `docs/architecture`: Target architecture, lifecycle, and integration guidance
- `docs/runbooks`: Operational runbooks for deployment and troubleshooting

## POC to Production Migration Map

The original POC remains at repository root and serves as a compatibility
reference while production apps are scaffolded.

- `XFlows.html` -> `apps/web` (frontend shell and bundling pipeline)
- `app.jsx` -> `apps/web` (state management and editor runtime)
- `catalog.js` -> `packages/workflow-spec` + worker activity registry
- `codegen.js` -> `packages/workflow-spec` + Temporal workflow executor
- `component-panel.jsx`, `canvas.jsx`, `param-modal.jsx`, `steps-pane.jsx` ->
  `apps/web` component tree

## Execution Model

- Authoring and testing: Web client calls API.
- Orchestration: API starts Temporal workflows.
- Execution: Worker activities perform node-level work.
- Inference: LiteLLM routes requests to OpenAI, Ollama, or vLLM.
- Observability: Langfuse traces and Prometheus metrics.
