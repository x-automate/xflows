from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "XFlows API"
    environment: str = "dev"
    temporal_host_port: str = "temporal:7233"
    temporal_task_queue: str = "xflows-workflows"
    temporal_namespace: str = "default"
    internal_api_token: str | None = None
    # Rotation set (XF-12): any of these tokens is accepted for worker->API
    # callbacks; revoke by removing from the list, add the new one first.
    internal_api_tokens: str = ""
    litellm_base_url: str = "http://litellm:4000"
    litellm_api_key: str | None = None
    litellm_master_key: str | None = None
    litellm_model_alias: str = "gpt-4o-mini"
    cors_origins: str = "http://localhost:4173,http://127.0.0.1:4173"
    database_url: str = "postgresql://postgres:postgres@postgres:5432/xflows"
    redis_url: str = "redis://redis:6379/0"
    # Postgres is often still starting when the API boots (or its DNS name is not
    # resolvable yet). Retry for roughly db_connect_max_attempts * backoff before
    # giving up, so ordinary startup races do not need a container restart.
    db_connect_max_attempts: int = 5
    db_connect_backoff_s: float = 1.0
    persistence_mode: str = "postgres"
    persistence_reads_from_sql: bool = True
    schema_auto_migrate: bool = True
    cache_ttl_seconds: int = 30
    idempotency_ttl_seconds: int = 86400

    # AuthN/AuthZ (XU-7 / XF-04): "off" is dev-only; "token" requires
    # Authorization: Bearer <token> and resolves a role + project scope.
    auth_mode: str = "off"
    # Entries: name|token|role|projects (projects: "*" or comma ids)
    api_callers: str = ""

    # Trigger execution (XU-8): scheduler tick interval for time triggers.
    trigger_scheduler_interval_s: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def internal_token_set(self) -> set[str]:
        tokens = {self.internal_api_token} if self.internal_api_token else set()
        tokens |= {t.strip() for t in self.internal_api_tokens.split(",") if t.strip()}
        return {t for t in tokens if t}


settings = Settings()
