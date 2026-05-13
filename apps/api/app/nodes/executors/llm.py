from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult


class ChatLikeExecutor(BaseNodeExecutor):
    component_ids = ("LLM", "OpenAIChat", "AnthropicChat", "ReActAgent")

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        content = await context.llm_chat(
            str(input_payload.get("value", "")),
            input_payload.get("system") if isinstance(input_payload.get("system"), str) else None,
            str(params.get("model")) if params.get("model") is not None else None,
            float(params.get("temperature", 0.2)),
        )
        return NodeExecutionResult(value=content)
