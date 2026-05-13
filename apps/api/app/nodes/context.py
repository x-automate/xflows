from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


LlmChatCallable = Callable[[str, str | None, str | None, float], Awaitable[str]]
HttpRequestCallable = Callable[[str, str], Awaitable[str]]


@dataclass(slots=True)
class NodeExecutionContext:
    run_id: str
    trace_id: str | None
    user_input: str
    llm_chat: LlmChatCallable
    http_request: HttpRequestCallable
    runtime_config: dict[str, Any]
