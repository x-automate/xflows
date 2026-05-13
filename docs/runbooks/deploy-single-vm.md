# Deploy XFlows on a Single VM (Docker Compose)

## Prerequisites

- Docker Engine + Compose plugin installed
- At least 8 vCPU, 16 GB RAM for core profile
- Public DNS + TLS termination handled by reverse proxy (optional but recommended)

## 1) Configure environment

```bash
cd deploy/docker
cp .env.example .env
```

Update required secrets in `.env`:

- `POSTGRES_PASSWORD`
- `LITELLM_MASTER_KEY`
- `OPENAI_API_KEY` (if using OpenAI)
- `LANGFUSE_*` keys (if observability profile enabled)

Recommended persistence settings:

- `PERSISTENCE_MODE=postgres` (or `dual` during phased rollout)
- `PERSISTENCE_READS_FROM_SQL=true`
- `DATABASE_URL=postgresql://...`
- `REDIS_URL=redis://...`
- `SCHEMA_AUTO_MIGRATE=true`

## 2) Start core stack

```bash
docker compose --profile core up -d --build
```

Core endpoints:

- Web: `http://localhost:4173`
- API: `http://localhost:8000/health`
- Temporal UI: `http://localhost:8080`
- LiteLLM: `http://localhost:4000`

## 3) Start observability profile (optional)

```bash
docker compose --profile core --profile observability up -d
```

Observability endpoints:

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Langfuse: `http://localhost:3001`

## 4) Verify runtime health

```bash
docker compose ps
docker compose logs api --tail=100
docker compose logs worker --tail=100
```

## 5) Operational notes

- If Temporal is not ready yet, API falls back to local run simulation for startup continuity.
- Configure provider models and keys in LiteLLM before load testing.
- API persistence now uses Postgres as source of truth and Redis for idempotency/cache acceleration.
- `PERSISTENCE_MODE=dual` can be used for migration verification before full SQL cutover.

## 6) Backup and retention

- **Postgres backups**: run daily `pg_dump` for the `xflows` database and keep at least 7 snapshots.
- **Restore drill**: rehearse monthly restore to a staging VM and verify `/projects` and `/runs/{id}` endpoints.
- **Run event retention**: archive or prune `run_events` older than your compliance window (for example 30-90 days).
- **Redis expectations**: treat Redis as ephemeral; never rely on Redis-only data for long-term recovery.
