from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from .config import settings

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - optional dependency behavior
    Langfuse = None  # type: ignore[assignment]


@dataclass
class TracingContext:
    trace_id: str
    run_id: str


class LangfuseTracer:
    def __init__(self) -> None:
        if Langfuse and settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key:
            self.client = Langfuse(
                host=settings.langfuse_host,
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
            )
        else:
            self.client = None

    @asynccontextmanager
    async def span(self, ctx: TracingContext, name: str, input_payload: dict | None = None) -> AsyncIterator[None]:
        if not self.client:
            yield
            return

        generation = self.client.generation(
            trace_id=ctx.trace_id,
            name=name,
            metadata={"runId": ctx.run_id},
            input=input_payload or {},
        )
        try:
            yield
            generation.update(level="DEFAULT")
        except Exception as exc:
            generation.update(level="ERROR", status_message=str(exc))
            raise
        finally:
            self.client.flush()
