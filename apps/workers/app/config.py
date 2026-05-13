from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    temporal_host_port: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "xflows-workflows"

    litellm_base_url: str = "http://litellm:4000"
    litellm_model_alias: str = "gpt-4o-mini"
    litellm_api_key: str = "not-used-for-local-proxy"

    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    api_base_url: str = "http://api:8000"
    internal_api_token: str | None = None


settings = Settings()
