from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult


class HttpRequestExecutor(BaseNodeExecutor):
    component_ids = ("HttpRequest",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        method = str(params.get("method", "GET"))
        url = str(params.get("url", ""))
        if not url:
            raise ValueError("HttpRequest requires a URL")
        response_text = await context.http_request(method, url)
        return NodeExecutionResult(value=response_text)
