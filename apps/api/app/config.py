from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "XFlows API"
    environment: str = "dev"
    temporal_host_port: str = "temporal:7233"
    temporal_task_queue: str = "xflows-workflows"
    temporal_namespace: str = "default"
    internal_api_token: str | None = None
    litellm_base_url: str = "http://litellm:4000"
    litellm_api_key: str | None = None
    litellm_master_key: str | None = None
    litellm_model_alias: str = "gpt-4o-mini"
    cors_origins: str = "http://localhost:4173,http://127.0.0.1:4173"
    database_url: str = "postgresql://postgres:postgres@postgres:5432/xflows"
    redis_url: str = "redis://redis:6379/0"
    persistence_mode: str = "postgres"
    persistence_reads_from_sql: bool = True
    schema_auto_migrate: bool = True
    cache_ttl_seconds: int = 30
    idempotency_ttl_seconds: int = 86400

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
