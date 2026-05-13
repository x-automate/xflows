from __future__ import annotations

from .executors import ChatLikeExecutor, HttpRequestExecutor, InputExecutor, OutputExecutor, PassthroughExecutor, PromptTemplateExecutor
from .registry import NodeRegistry


def create_default_registry() -> NodeRegistry:
    default_executor = PassthroughExecutor()
    registry = NodeRegistry(default_executor=default_executor)
    registry.register(InputExecutor())
    registry.register(PromptTemplateExecutor())
    registry.register(ChatLikeExecutor())
    registry.register(HttpRequestExecutor())
    registry.register(OutputExecutor())
    return registry
