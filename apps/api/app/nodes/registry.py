from __future__ import annotations

from typing import Any

from .base import BaseNodeExecutor
from .context import NodeExecutionContext


class NodeRegistry:
    def __init__(self, default_executor: BaseNodeExecutor) -> None:
        self._executors: dict[str, BaseNodeExecutor] = {}
        self._default_executor = default_executor

    def register(self, executor: BaseNodeExecutor) -> None:
        for component_id in executor.component_ids:
            self._executors[component_id] = executor

    async def dispatch(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        component_id = str(node.get("componentId", ""))
        executor = self._executors.get(component_id, self._default_executor)
        result = await executor.execute(node=node, input_payload=input_payload, context=context)
        return result.to_payload()
