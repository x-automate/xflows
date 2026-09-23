# Configuration

Every environment variable per service. Pydantic settings with `.env` file support
(`apps/api/app/config.py`, `apps/workers/app/config.py`); the web app uses Vite env vars baked
at build time. Defaults below match the code; deployment defaults are in
`deploy/docker/.env.example`.

## API (`apps/api`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_NAME` | `XFlows API` | FastAPI title |
| `ENVIRONMENT` | `dev` | deployment tag |
| `TEMPORAL_HOST_PORT` | `temporal:7233` | Temporal frontend address |
| `TEMPORAL_TASK_QUEUE` | `xflows-workflows` | task queue the API starts workflows on |
| `TEMPORAL_NAMESPACE` | `default` | |
| `INTERNAL_API_TOKEN` | unset | guards `POST /internal/runs/{runId}/events` (unset = no check) |
| `LITELLM_BASE_URL` | `http://litellm:4000` | fallback LLM base URL |
| `LITELLM_API_KEY` / `LITELLM_MASTER_KEY` | unset | auth for LiteLLM calls (fallback order: runtimeConfig key → `LITELLM_API_KEY` → `LITELLM_MASTER_KEY`) |
| `LITELLM_MODEL_ALIAS` | `gpt-4o-mini` | server default model |
| `CORS_ORIGINS` | `http://localhost:4173,http://127.0.0.1:4173` | comma-separated allowed origins |
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/xflows` | Postgres DSN |
| `REDIS_URL` | `redis://redis:6379/0` | cache DSN (optional at runtime) |
| `PERSISTENCE_MODE` | `postgres` | `memory` \| `postgres` \| `dual` |
| `PERSISTENCE_READS_FROM_SQL` | `true` | used by `dual` mode |
| `SCHEMA_AUTO_MIGRATE` | `true` | apply embedded schema on startup |
| `CACHE_TTL_SECONDS` | `30` | Redis cache TTL |
| `IDEMPOTENCY_TTL_SECONDS` | `86400` | idempotency key lifetime (24 h) |

## Worker (`apps/workers`)

| Variable | Default | Meaning |
|---|---|---|
| `TEMPORAL_HOST_PORT` | `temporal:7233` | |
| `TEMPORAL_NAMESPACE` | `default` | |
| `TEMPORAL_TASK_QUEUE` | `xflows-workflows` | queue polled by the worker |
| `LITELLM_BASE_URL` | `http://litellm:4000` | model router endpoint |
| `LITELLM_MODEL_ALIAS` | `gpt-4o-mini` | terminal fallback in model resolution |
| `LITELLM_API_KEY` | `not-used-for-local-proxy` | bearer token for LiteLLM (overridden by `runtimeConfig.litellmApiKey`) |
| `LANGFUSE_HOST` | unset | Langfuse tracing enabled only when host + both keys are set |
| `LANGFUSE_PUBLIC_KEY` | unset | |
| `LANGFUSE_SECRET_KEY` | unset | |
| `API_BASE_URL` | `http://api:8000` | where node/run events are POSTed |
| `INTERNAL_API_TOKEN` | unset | sent as `x-internal-token` on event POSTs |

Worker processes also bind a Prometheus HTTP server on port **9464**.

## Web (`apps/web`)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | API base for REST + SSE; **build-time** (passed as a Docker build arg) |

Dev server: Vite on port 5173 (`npm run dev`); the production image serves `dist/` via `serve`
on port 4173.

## Temporal Server (compose)

Set in `deploy/docker/docker-compose.yml`:

- `DB=postgres12`, `DB_PORT=5432`, `POSTGRES_SEEDS=postgres`, `POSTGRES_USER`, `POSTGRES_PWD`
- Image `temporalio/auto-setup:1.25.2`; UI `temporalio/ui:2.31.2` on port 8081.

## LiteLLM (`deploy/docker/litellm_config.yaml`)

- Default model entry: alias `gpt-4o-mini` → `openai/gpt-4o-mini`,
  `api_key: os.environ/OPENAI_API_KEY`.
- `router_settings.routing_strategy: simple-shuffle`.
- The proxy passes model names through verbatim; to serve Ollama/vLLM add aliases pointing at
  those backends (blueprint in [integrations](../architecture/integrations.md)).
- Auth: `LITELLM_MASTER_KEY` (used by XFlows as the default bearer when no runtime key is set)
  and `OPENAI_API_KEY` (for the OpenAI backend).

## Docker Compose Profiles

| Profile | Services |
|---|---|
| `core` | postgres, redis, temporal, temporal-ui, litellm, api, worker, web |
| `observability` | clickhouse, langfuse, prometheus, grafana |

Ports at a glance:

| Port | Service |
|---|---|
| 4173 | web (5173 = Vite dev) |
| 8000 | api |
| 9464 | worker metrics |
| 7233 | temporal frontend |
| 8081 | temporal-ui |
| 4000 | litellm |
| 5432 | postgres |
| 6379 | redis |
| 9090 | prometheus |
| 3000 | grafana |
| 3001 | langfuse (→ container 3000) |
| 8123 / 9000 | clickhouse HTTP / native |

Full service table: [deployment](../deployment/docker-compose.md).
