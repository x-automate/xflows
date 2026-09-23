# Getting Started

This guide walks you from zero to a running workflow: start the stack with Docker Compose,
create a project, build a flow, and run it.

## Prerequisites

- Docker Engine + Compose plugin (the single-VM path uses `deploy/docker/docker-compose.yml`)
- 8 vCPU / 16 GB RAM recommended for the core profile
- An OpenAI API key (or any provider reachable via LiteLLM: Ollama, vLLM, …)

## 1. Start the Stack

```bash
cd deploy/docker
cp .env.example .env
# edit .env: POSTGRES_PASSWORD, LITELLM_MASTER_KEY, OPENAI_API_KEY, optionally LANGFUSE_*
docker compose --profile core up -d --build
```

Core services and URLs:

| Service | URL | What it is |
|---|---|---|
| Web UI | http://localhost:4173 | Authoring + run UX |
| API | http://localhost:8000 | FastAPI gateway (also `/metrics`, `/health`) |
| Temporal UI | http://localhost:8081 | Inspect workflow histories |
| LiteLLM | http://localhost:4000 | Model routing proxy |

Add the observability stack (Langfuse, Prometheus, Grafana, ClickHouse) with:

```bash
docker compose --profile core --profile observability up -d
```

| Service | URL |
|---|---|
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Langfuse | http://localhost:3001 |

Verify health:

```bash
docker compose ps
curl http://localhost:8000/health
# {"status": "ok", "temporal": "connected"}
```

`temporal: connected` confirms the orchestration path. If Temporal is not reachable, the API
falls back to **local execution** of the same node engine — runs still work, events still stream.

## 2. Create a Project

Open http://localhost:4173 and click **New Project** on the Dashboard. You get a project
workspace with tabs:

- **Flow** — the canvas editor (default tab)
- **Configs** — credentials and global model parameters
- **Trigger** — trigger table
- **Logs** — run history

URL layout (see [Feature map](features/overview.md#routes)):

- `/project/{id}/flow`, `/project/{id}/configs`, `/project/{id}/trigger`, `/project/{id}/logs`
- `/project/{id}/run/{runId}` — run a workflow and watch results
- `/project/{id}/view/{runId}` — live read-only view of a running workflow

## 3. Build a Workflow

On the Flow tab, assemble a graph on the canvas:

1. Drag an **Input** node from the left component panel.
2. Drag a **Prompt** (PromptTemplate) node and connect `Input → Prompt`.
3. Drag an **LLM** container node. Drop a provider chip inside it — **OpenAI**, **Claude**, or
   **LiteLLM**. The provider becomes the container's executable component at run time.
4. Drag an **Output** node and connect the chain:
   `Input → Prompt → LLM → Output`.
5. Click a node to edit its parameters in the right **Properties** panel (or use ⚙ in the
   **Steps** tab).

The editor validates as you work (exactly one Input, exactly one Output, acyclic data graph,
providers must sit inside a container, no disconnected nodes). See
[Workflow editor](features/workflow-editor.md) for every interaction: pan/zoom, config slots,
undo/redo, keyboard shortcuts, JSON import/export.

## 4. Configure Credentials (Configs tab)

The Configs tab is dynamic: it renders fields required by the nodes present in your flow.
For example, with a LiteLLM provider in the graph you must fill:

- `LiteLLM API key` (password)
- `LiteLLM base URL` (default `http://localhost:4000`)
- `Default LiteLLM model` (default `gpt-4o-mini`)

These values are saved to the project (`configs`) and passed into every run as
`metadata.runtimeConfig`. Never enter API keys per-run — manage them once per project.
See [Projects, configs & triggers](features/projects-configs-triggers.md).

## 5. Run It

Two ways:

1. **From the editor** — right pane → **Test** tab → enter test input → **Run workflow**.
   The editor creates a workflow (`wf_web_editor_<timestamp>`), starts the run, and renders a
   live trace with per-node durations, outputs, and final result.
2. **From the project** — `/project/{id}/run/new` → enter the run input → start. You land on the
   run page; a **View** link opens the live read-only canvas visualization of the same run.

While it runs, the worker:

- executes each node as a Temporal activity (schedule-to-close 120s, up to 3 attempts),
- emits `node_started` / `node_succeeded` / `node_failed` events back to the API,
- routes LLM calls through LiteLLM with a model fallback chain.

Everything arrives in the browser over **Server-Sent Events** (`GET /runs/{runId}/events`),
supplemented by run polling. See [Runs](features/runs.md) and [Run events](reference/run-events.md).

## 6. Inspect Results

- **Logs tab** — run table with status badges, per-run event history (expand Details).
- **Temporal UI** (http://localhost:8081) — Temporal-side history of the workflow
  `XFlowsWorkflow.run` (workflow id format `{workflowId}:{runId}`).
- **Langfuse** (http://localhost:3001) — one trace per run, one span per node
  (`node:{componentId}`), with input/output and metadata.
- **Grafana/Prometheus** — API and worker dashboards; alert rules in
  `deploy/docker/prometheus-alerts.yml`.

## 7. Run the Regression Eval (optional)

```bash
python -m pip install -r tools/evals/requirements.txt
python tools/evals/regression_eval.py
```

The harness POSTs test inputs to `POST /workflows/wf_support_assistant/runs`, polls to
completion, and checks the output against expected substrings. It exits non-zero on failure and
prints `{total, failures, p95_latency_seconds}`. See [Local development](guides/development.md#evaluation-harness).

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `GET /health` shows `temporal: disconnected` | Temporal still starting (auto-setup can take ~30s); check `docker compose logs temporal`. Runs still work via the local fallback path. |
| Node errors mention `LiteLLM chat failed (status=401...)` | Wrong `litellmApiKey` in project Configs or `LITELLM_MASTER_KEY` mismatch in `.env`. |
| Node errors include provider/model + response body | Intended: LiteLLM model names are sent **exactly as configured** — check the exact alias your LiteLLM exposes (e.g. `openai/gpt-4o-mini` vs `gpt-4o-mini`). |
| Run stuck in `queued` | Worker not up (`docker compose logs worker`) or Temporal task queue mismatch (`xflows-workflows`). |
| UI shows old data after backend restart | The web app keeps a localStorage cache (`xflows_projects`); it reconciles with the API automatically on each load. |

Next: read the [Architecture overview](architecture/overview.md) to understand how everything
fits together, or the [REST API reference](reference/api-reference.md) to drive the API directly.
