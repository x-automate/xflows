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
        runtime_config = context.runtime_config or {}
        model_hint = (
            str(params.get("model"))
            if params.get("model") is not None
            else (
                str(runtime_config.get("litellmModel"))
                if runtime_config.get("litellmModel") is not None
                else None
            )
        )
        temperature = float(params.get("temperature", runtime_config.get("temperature", 0.2)))
        llm_result = await context.llm_chat(
            str(input_payload.get("value", "")),
            input_payload.get("system") if isinstance(input_payload.get("system"), str) else None,
            model_hint,
            temperature,
        )
        return NodeExecutionResult(
            value=llm_result.get("content", ""),
            metadata={
                "provider": llm_result.get("provider"),
                "model": llm_result.get("model") or model_hint,
                "usage": llm_result.get("usage", {}),
            },
        )
