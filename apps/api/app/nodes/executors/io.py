from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult


class InputExecutor(BaseNodeExecutor):
    component_ids = ("Input",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        return NodeExecutionResult(value=context.user_input)


class PromptTemplateExecutor(BaseNodeExecutor):
    component_ids = ("PromptTemplate",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        template = str(params.get("template", "{input}"))
        rendered = template.replace("{input}", str(input_payload.get("value", "")))
        system_prompt = str(params.get("system", "You are a helpful assistant."))
        return NodeExecutionResult(value=rendered, metadata={"system": system_prompt})


class OutputExecutor(BaseNodeExecutor):
    component_ids = ("Output",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        return NodeExecutionResult(value=input_payload.get("value", ""))


class PassthroughExecutor(BaseNodeExecutor):
    component_ids = ()

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        return NodeExecutionResult(value=input_payload.get("value", ""))
