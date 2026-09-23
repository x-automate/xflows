# Local Development

How to run each app outside Docker, run the tests, and use the eval harness.

## Prerequisites

- Python 3.11 (API + workers), Node 20 (web), and optionally a local Postgres/Redis/Temporal
  (or run just the infrastructure via Docker Compose and the apps natively).

## Infrastructure Only (fast loop)

```bash
cd deploy/docker
cp .env.example .env
docker compose --profile core up -d postgres redis temporal litellm
```

Then run the apps natively against those services.

## API

```bash
cd apps/api
python -m venv .venv && .venv\Scripts\activate        # Windows; source .venv/bin/activate on Unix
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Settings are read from `.env` (see [configuration](../reference/configuration.md#api-appsapi)).
For a fully standalone dev loop, set `PERSISTENCE_MODE=memory` — no Postgres/Redis needed, and
Temporal absence just triggers the local fallback execution path (runs still work end-to-end).

Interactive API docs: http://localhost:8000/docs (FastAPI auto-docs).

## Workers

```bash
cd apps/workers
pip install -r requirements.txt
python -m app.worker
```

Requires Temporal reachable at `TEMPORAL_HOST_PORT`; LiteLLM at `LITELLM_BASE_URL` for LLM nodes.
Metrics bind to port 9464. Configure `LANGFUSE_*` to enable real tracing spans.

## Web

```bash
cd apps/web
npm install
npm run dev        # Vite dev server on http://localhost:5173
npm run build      # production bundle in dist/ (served on 4173 by the Docker image)
```

Set `VITE_API_BASE_URL` (default `http://localhost:8000`) via a `.env` file in `apps/web` or the
environment before building. The UI degrades gracefully without the API (localStorage mode) —
see [projects feature](../features/projects-configs-triggers.md#persistence-behavior).

## Tests

Node-engine test suites exist in both Python apps (unittest):

```bash
# apps/api
python -m unittest discover -s tests
# apps/workers
python -m unittest discover -s tests
```

Coverage today (`tests/test_nodes_engine.py` in each app): registry dispatch (chat node with
fake `llm_chat`/`http_request`), graph normalization (config edges dropped; nested provider child
promotion), end-to-end runner (`Input → PromptTemplate → Output`), `LiteLLM` metadata, required
URL validation for HTTP/API-caller nodes, and webhook/tracer passthrough semantics.

There is no test framework configured for the web app yet.

## Evaluation Harness

```bash
python -m pip install -r tools/evals/requirements.txt   # requests
python tools/evals/regression_eval.py
```

- Targets `http://localhost:8000` (edit `API_BASE_URL` in the script) and workflow
  `wf_support_assistant` — create it first by POSTing
  `packages/workflow-spec/examples/basic-workflow.json` content to `POST /workflows`.
- Cases come from `tools/evals/testcases.json`:
  `{name, input, expect_contains_any}` — a pass requires run status `succeeded` **and** the
  lowercased output containing at least one expected substring; an empty array checks status
  only.
- Polls `GET /runs/{runId}` every 0.5 s, 90 s cap per case; output:
  `{total, failures, p95_latency_seconds}`; exit code 1 on any failure.

## Code Style Notes

- Python apps use `from __future__ import annotations`, Pydantic v2 camelCase models, and module
  loggers; no linter config is committed yet — mirror the existing style.
- The web app is plain JavaScript (no TypeScript) with hand-written CSS (`index.css`,
  `features/workflow/workflow.css` using a `wf-` namespace). No state/UI libraries — components
  + hooks only.

## Where to Make Common Changes

| Change | Files |
|---|---|
| New node type (end-to-end) | catalog JSON + executors + factory + tests in **both** `apps/api` and `apps/workers` — guide: [generic nodes backend](../architecture/generic-nodes-backend.md#how-to-add-a-new-node-type) |
| New API endpoint | `apps/api/app/main.py` (+ models in `app/models.py`, store method in `app/store.py`) |
| New project config field | `projectConfigs` entry in `apps/web/src/features/workflow/catalog/node-registry.json` |
| Model routing/fallback chain | `apps/workers/app/provider_router.py`; provider aliases in `deploy/docker/litellm_config.yaml` |
| Alert rules | `deploy/docker/prometheus-alerts.yml` |
| Compose changes | `deploy/docker/docker-compose.yml` (+ `.env.example`) |
