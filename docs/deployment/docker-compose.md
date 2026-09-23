# Deployment — Docker Compose

Stack definition: `deploy/docker/docker-compose.yml` (project name `xflows`). Profiles:
**core** (runtime) and **observability** (optional monitoring/tracing). Step-by-step ops runbook:
[deploy-single-vm](../runbooks/deploy-single-vm.md).

## Startup

```bash
cd deploy/docker
cp .env.example .env    # fill POSTGRES_PASSWORD, LITELLM_MASTER_KEY, OPENAI_API_KEY, LANGFUSE_*
docker compose --profile core up -d --build
# optional:
docker compose --profile core --profile observability up -d
```

## Services (core profile)

| Service | Image / Build | Port(s) | Depends on (healthy) | Notes |
|---|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 | — | creds/db from env; volume `postgres_data`; `pg_isready` healthcheck |
| `redis` | `redis:7-alpine` | 6379 | — | `--appendonly yes`; volume `redis_data`; ping healthcheck |
| `temporal` | `temporalio/auto-setup:1.25.2` | 7233 | postgres | auto-setup against Postgres |
| `temporal-ui` | `temporalio/ui:2.31.2` | 8081 | — | points at `temporal:7233` |
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | 4000 | redis | mounts `litellm_config.yaml` read-only; env `LITELLM_MASTER_KEY`, `OPENAI_API_KEY` |
| `api` | build `apps/api` | 8000 | postgres, redis (+ temporal started) | healthcheck `GET /health`; full env in [configuration](../reference/configuration.md#api-appsapi) |
| `worker` | build `apps/workers` | 9464 (metrics) | api (healthy), litellm + temporal (started) | polls `xflows-workflows`; `LITELLM_API_KEY=$LITELLM_MASTER_KEY` |
| `web` | build `apps/web` (build arg `VITE_API_BASE_URL`) | 4173 | api (healthy) | static bundle served by `serve` |

## Services (observability profile)

| Service | Image | Port(s) | Notes |
|---|---|---|---|
| `clickhouse` | `clickhouse/clickhouse-server:24.8-alpine` | 8123, 9000 | Langfuse v2 storage; volume `clickhouse_data` |
| `langfuse` | `langfuse/langfuse:2` | **3001 → 3000** | Postgres + Redis + ClickHouse wired; seeds org/project `xflows` via `LANGFUSE_INIT_*` keys; telemetry off |
| `prometheus` | `prom/prometheus:v2.54.1` | 9090 | scrapes `api:8000/metrics` and `worker:9464/metrics` (15s interval); loads `prometheus-alerts.yml` |
| `grafana` | `grafana/grafana:11.2.2` | 3000 | admin creds from env; volume `grafana_data` |

Volumes: `postgres_data`, `redis_data`, `clickhouse_data`, `grafana_data`.

## Startup Ordering

Healthchecks gate the dependency chain so services come up safely:

```
postgres/redis → temporal → api → worker → web
                ↘ litellm ↗
```

Notable: `worker` depends on a **healthy api** (it POSTs events to it) and litellm/temporal
started; `api` tolerates a not-yet-ready Temporal (local fallback keeps test runs working).

## Networking

All services share the default compose network and use service DNS names:

- Web → API: `VITE_API_BASE_URL` (baked into the bundle at build time).
- API → services: `postgres:5432`, `redis:6379`, `temporal:7233`.
- Worker → API: `API_BASE_URL=http://api:8000`; → LiteLLM: `LITELLM_BASE_URL=http://litellm:4000`.
- From the host, browser-side API calls hit `http://localhost:8000` — keep
  `CORS_ORIGINS`/`VITE_API_BASE_URL` aligned with how users reach the API.

## Prometheus Rules

`deploy/docker/prometheus.yml` — two scrape jobs (`xflows-api`, `xflows-worker`), 15 s interval.

`prometheus-alerts.yml` (group `xflows-alerts`):

| Alert | Expression summary | Severity |
|---|---|---|
| `XFlowsApiDown` | `up{job="xflows-api"} == 0` for 2m | critical |
| `XFlowsWorkerDown` | `up{job="xflows-worker"} == 0` for 2m | critical |
| `XFlowsRunCreateLatencyHigh` | P95 `xflows_run_create_latency_seconds_bucket` over 5m > 2s for 10m | warning |
| `XFlowsNodeErrorRateHigh` | `xflows_node_executions_total{status="error"}` share > 5% for 10m | warning |

## LiteLLM Config

`litellm_config.yaml` (mounted read-only):

```yaml
model_list:
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
router_settings:
  routing_strategy: simple-shuffle
```

- XFlows sends model names **verbatim** — add an entry per alias you plan to use (e.g.
  `openai/gpt-4o`, `ollama/llama3.1:8b`, `vllm/meta-llama/Llama-3.1-8B-Instruct` for the worker's
  fallback chain).
- Configure provider keys before load testing.

## Environment File

`.env.example` covers: web/API (`VITE_API_BASE_URL`, `INTERNAL_API_TOKEN`, `CORS_ORIGINS`,
persistence settings), core DB (`POSTGRES_*`, `DATABASE_URL`, `REDIS_URL`), LiteLLM
(`LITELLM_MASTER_KEY`, `OPENAI_API_KEY`), Langfuse (`LANGFUSE_DB`, `LANGFUSE_HOST`,
`LANGFUSE_PUBLIC_KEY/SECRET_KEY`, `LANGFUSE_SALT`, `LANGFUSE_NEXTAUTH_SECRET`,
`CLICKHOUSE_PASSWORD`), Grafana (`GRAFANA_ADMIN_USER/PASSWORD`, default admin/admin).

Every variable's meaning: [configuration reference](../reference/configuration.md).

## Operations Checklist

- Replace default credentials before exposing anything beyond localhost.
- Health verification: `docker compose ps`, `docker compose logs api/worker --tail=100`,
  `curl localhost:8000/health`.
- Backups: daily `pg_dump` of the `xflows` DB (keep ≥7 snapshots); rehearse restores; prune
  `run_events` per your retention window. Treat Redis as ephemeral. Details in the
  [runbook](../runbooks/deploy-single-vm.md#6-backup-and-retention).
- Scaling the worker: add replicas — they share the `xflows-workflows` task queue; runs are
  distributed by Temporal.
