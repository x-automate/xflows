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
- Temporal UI: `http://localhost:8081`
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

## 5) Troubleshooting startup

### `Cannot reach Postgres at <host>:5432/<db>`

The API refuses to start without its database — it will not silently fall back
to in-memory, because that would look healthy while losing every write. The
message names the host it tried and what to change; the DSN is printed as
`host:port/database`, never with credentials.

It retries first (`DB_CONNECT_MAX_ATTEMPTS` × `DB_CONNECT_BACKOFF_S`, ≈15 s by
default), so an ordinary startup race resolves itself. Bad credentials and a
missing database fail immediately instead, since no amount of waiting fixes them.

| Message says | Cause | Fix |
|---|---|---|
| *the host name `postgres` does not resolve* | The API is not on the same compose network as the database. | Start both together: `docker compose --profile core up`. Running the API on its own — a bare `uvicorn`, or `docker run` without the compose network — cannot resolve `postgres`. |
| *the host name … does not resolve* (an external host) | Typo, or the container has no DNS route to a managed database. | Check `DATABASE_URL`, and that the VM can reach the database's network. |
| *the host resolved but refused the connection* | Postgres is not accepting connections, or the port is wrong. | `docker compose ps postgres`, then check the port in `DATABASE_URL`. |
| *the server rejected the credentials* | `.env` no longer matches the database. | An existing `postgres_data` volume keeps the credentials it was **initialised** with; changing `.env` afterwards does not update them. Either restore the original values or recreate the volume. |

Running the API **outside** compose against the compose database: keep the
database's published port and point at it directly —
`DATABASE_URL=postgresql://xflows:xflows_dev_password@localhost:5432/xflows`.
For a throwaway instance with no database at all, `PERSISTENCE_MODE=memory`
starts the API with an in-memory store (nothing survives a restart).

Note that `.env.example` ships `DATABASE_URL=…@postgres:5432/…`, which is
correct **inside** compose and unresolvable outside it.

## 6) Operational notes

- If Temporal is not ready yet, API falls back to local run simulation for startup continuity.
- Configure provider models and keys in LiteLLM before load testing.
- API persistence now uses Postgres as source of truth and Redis for idempotency/cache acceleration.
- `PERSISTENCE_MODE=dual` can be used for migration verification before full SQL cutover.

## 7) Backup and retention

- **Postgres backups**: run daily `pg_dump` for the `xflows` database and keep at least 7 snapshots.
- **Restore drill**: rehearse monthly restore to a staging VM and verify `/projects` and `/runs/{id}` endpoints.
- **Run event retention**: archive or prune `run_events` older than your compliance window (for example 30-90 days).
- **Redis expectations**: treat Redis as ephemeral; never rely on Redis-only data for long-term recovery.
