from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .context import NodeExecutionContext
from .result import NodeExecutionResult


class BaseNodeExecutor(ABC):
    component_ids: tuple[str, ...] = ()

    @abstractmethod
    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        raise NotImplementedError
