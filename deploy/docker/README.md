# Docker Deployment

## Profiles

- `core`: web, api, worker, temporal, temporal-ui, postgres, redis, litellm
- `observability`: langfuse, clickhouse, prometheus, grafana

## Commands

```bash
cd deploy/docker
cp .env.example .env
docker compose --profile core up -d --build
docker compose --profile core --profile observability up -d
```

## Notes

- `worker` uses LiteLLM as the only model routing endpoint.
- Healthchecks gate startup ordering for critical dependencies.
- Replace default credentials before exposing the VM.
