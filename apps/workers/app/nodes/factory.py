from __future__ import annotations

from .executors import (
    ApiCallerExecutor,
    ChatLikeExecutor,
    HttpRequestExecutor,
    InputExecutor,
    LangfuseTracerExecutor,
    LangsmithTracerExecutor,
    LiteLlmExecutor,
    OutputExecutor,
    PassthroughExecutor,
    PromptTemplateExecutor,
    WebhookTriggerExecutor,
)
from .registry import NodeRegistry


def create_default_registry() -> NodeRegistry:
    default_executor = PassthroughExecutor()
    registry = NodeRegistry(default_executor=default_executor)
    registry.register(InputExecutor())
    registry.register(PromptTemplateExecutor())
    registry.register(ChatLikeExecutor())
    registry.register(LiteLlmExecutor())
    registry.register(HttpRequestExecutor())
    registry.register(ApiCallerExecutor())
    registry.register(WebhookTriggerExecutor())
    registry.register(LangfuseTracerExecutor())
    registry.register(LangsmithTracerExecutor())
    registry.register(OutputExecutor())
    return registry
