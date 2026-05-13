from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from temporalio.client import Client

from .config import settings


@dataclass
class TemporalHandle:
    connected: bool
    reason: str | None = None


class TemporalGateway:
    def __init__(self) -> None:
        self._client: Client | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> TemporalHandle:
        if self._client:
            return TemporalHandle(connected=True)

        async with self._connect_lock:
            if self._client:
                return TemporalHandle(connected=True)
            try:
                self._client = await Client.connect(
                    settings.temporal_host_port,
                    namespace=settings.temporal_namespace,
                )
                return TemporalHandle(connected=True)
            except Exception as exc:  # pragma: no cover - startup resilience
                return TemporalHandle(connected=False, reason=str(exc))

    async def start_workflow(self, workflow_name: str, workflow_id: str, args: list[Any]) -> TemporalHandle:
        status = await self.connect()
        if not status.connected or not self._client:
            return status
        try:
            await self._client.start_workflow(
                workflow_name,
                args=args,
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
            )
            return TemporalHandle(connected=True)
        except Exception as exc:
            return TemporalHandle(connected=False, reason=str(exc))
