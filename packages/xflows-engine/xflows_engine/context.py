from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol


class XwsClientCallable(Protocol):
    """Seam for XWS tool calls; injected from the workers layer.

    The engine stays stdlib-only: it only knows this Protocol shape
    (mirroring ``app.xws.client.XWSClient.request``), never the httpx
    implementation itself.
    """

    def request(
        self,
        *,
        method: str,
        path: str,
        tool_class: str,
        run_id: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        idempotency_key: str | None = None,
        retry: bool = False,
    ) -> dict[str, Any]: ...


LlmChatCallable = Callable[..., Awaitable[dict[str, Any]]]
HttpRequestCallable = Callable[[str, str], Awaitable[str]]
# HITL seam: receives the approval request payload, resolves with a decision
# dict {"decision": "approved|rejected|request_changes|timeout", ...}. The
# Temporal workflow parks on signals; unit tests inject an immediate answer.
AwaitApprovalCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
# Child-workflow seam (docs 04 §2: apigen pipeline spawns apigen.validate /
# apigen.deploy). Receives {"workflowName", "input", "runtimeConfig"} and
# resolves with {"status": "succeeded|failed", "output": {...}}. Implemented
# by the workers layer via workflow.start_child_workflow; tests inject an
# immediate answer.
ChildWorkflowCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

SECRET_KEY_PATTERN = re.compile(r"api_?key|secret|token|password|credential", re.IGNORECASE)

# Components whose execution genuinely needs provider credentials. Every other
# node receives a runtime_config with secret-shaped keys stripped (fix XF-06:
# runtime config — including LLM keys — is no longer passed wholesale).
SECRET_BEARING_COMPONENTS = frozenset({
    "LLM",
    "LiteLLM",
    "ChatOllama",
    "AgentLoop",
    "HttpRequest",
    "ApiCaller",
})


def scoped_runtime_config(
    component_id: str,
    runtime_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a per-node runtime config with secret-shaped keys stripped.

    Nodes whose component genuinely needs provider credentials (the
    ``SECRET_BEARING_COMPONENTS`` set) receive the config unchanged; every
    other node gets a copy without keys matching ``SECRET_KEY_PATTERN``.
    """
    config = runtime_config or {}
    if not config or component_id in SECRET_BEARING_COMPONENTS:
        return dict(config or {})
    return {
        key: value
        for key, value in config.items()
        if not SECRET_KEY_PATTERN.search(key)
    }


@dataclass(slots=True)
class NodeExecutionContext:
    run_id: str
    trace_id: str | None
    user_input: str
    llm_chat: LlmChatCallable
    http_request: HttpRequestCallable
    runtime_config: dict[str, Any]
    xws_client: XwsClientCallable | None = None
    await_approval: AwaitApprovalCallable | None = None
    start_child_workflow: ChildWorkflowCallable | None = None
