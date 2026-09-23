from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    temporal_host_port: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "xflows-workflows"

    litellm_base_url: str = "http://litellm:4000"
    litellm_model_alias: str = "gpt-4o-mini"
    litellm_api_key: str = "not-used-for-local-proxy"
    litellm_fallback_models: str = "openai/gpt-4o,vllm/meta-llama/Llama-3.1-8B-Instruct,ollama/llama3.1:8b"

    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    api_base_url: str = "http://api:8000"
    internal_api_token: str | None = None

    xws_enabled: bool = True
    xws_base_url: str | None = None
    xws_region: str = "us-east-1"
    xws_service: str = "execute-api"
    xws_iam_endpoint: str | None = None
    xws_access_key_id: str | None = None
    xws_secret_access_key: str | None = None
    xws_session_duration_s: int = 900
    xws_role_arns: str = ""

    @property
    def xws_role_arn_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for pair in self.xws_role_arns.split(","):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            tool_class, _, arn = pair.partition("=")
            result[tool_class.strip()] = arn.strip()
        return result

    @property
    def xws_ready(self) -> bool:
        return bool(
            self.xws_enabled
            and self.xws_base_url
            and self.xws_iam_endpoint
            and self.xws_access_key_id
            and self.xws_secret_access_key
        )


settings = Settings()
