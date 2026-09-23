"""HITL approval node executor (docs 06 XU-5, 04 §5).

The engine-side executor builds the approval request payload and resolves a
normalized decision through the ``context.await_approval`` seam. The seam is
implemented by the workers layer (Temporal signal wait + timeout timer) and
faked in tests. The node's value is the decision payload so downstream
``when`` predicates can route on ``output.decision`` (04 §8 edge style).
"""

from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult

DEFAULT_SIGNAL_TIMEOUT_S = 259_200  # 72h (04 §5)
MAX_SIGNAL_TIMEOUT_S = 30 * 86_400  # 30 days

_DECISION_ALIASES = {
    "approve": "approved",
    "approved": "approved",
    "reject": "rejected",
    "rejected": "rejected",
    "request_changes": "request_changes",
    "request-changes": "request_changes",
    "timeout": "timeout",
    "escalate": "timeout",
}


def normalize_decision(raw: Any) -> str:
    """Map a raw decision to the canonical outcome, fail-closed to timeout."""
    if not isinstance(raw, str):
        return "timeout"
    return _DECISION_ALIASES.get(raw.strip().lower(), "timeout")


class ApprovalExecutor(BaseNodeExecutor):
    component_ids = ("Approval",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if context.await_approval is None:
            raise RuntimeError(
                "ApprovalExecutor requires an await_approval seam on the execution "
                "context (Temporal signal wait in the workers layer)"
            )
        params = node.get("params", {}) or {}
        try:
            timeout_s = int(params.get("signalTimeoutS", DEFAULT_SIGNAL_TIMEOUT_S))
        except (TypeError, ValueError):
            timeout_s = DEFAULT_SIGNAL_TIMEOUT_S
        timeout_s = max(1, min(timeout_s, MAX_SIGNAL_TIMEOUT_S))

        request: dict[str, Any] = {
            "runId": context.run_id,
            "nodeId": str(node.get("id", "")),
            "summary": str(params.get("summary") or input_payload.get("value") or "")[:200],
            "evidence": params.get("evidence", {}) if isinstance(params.get("evidence"), dict) else {},
            "notify": params.get("notify", {}) if isinstance(params.get("notify"), dict) else {},
            "signalTimeoutS": timeout_s,
        }
        raw_decision = await context.await_approval(request)
        decision = normalize_decision(
            raw_decision.get("decision") if isinstance(raw_decision, dict) else raw_decision
        )
        resolved = dict(raw_decision) if isinstance(raw_decision, dict) else {}
        resolved["decision"] = decision

        return NodeExecutionResult(
            value={
                "decision": decision,
                "reviewer": str(resolved.get("reviewer", "")),
                "comment": str(resolved.get("comment", "")),
                "evidence": resolved.get("evidence", {}),
            },
            metadata={
                "approval": {
                    "decision": decision,
                    "reviewer": str(resolved.get("reviewer", "")),
                    "signalTimeoutS": timeout_s,
                    "nodeId": request["nodeId"],
                },
            },
        )
