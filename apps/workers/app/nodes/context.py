from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


LlmChatCallable = Callable[[str, str | None, str | None, float], Awaitable[dict[str, Any]]]
HttpRequestCallable = Callable[[str, str], Awaitable[str]]


@dataclass(slots=True)
class NodeExecutionContext:
    run_id: str
    trace_id: str
    user_input: str
    llm_chat: LlmChatCallable
    http_request: HttpRequestCallable
