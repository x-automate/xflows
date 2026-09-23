"""HITL approval gate shared by the Temporal workflow (docs 06 XU-5, 04 §5).

The workflow parks an Approval node on a signal handler + timeout timer.
``ApprovalGate`` holds the recorded decisions (one per node id) and the
decision normalization lives in the shared engine package so the engine-side
executor and this gate agree on the canonical outcomes.

Only one approval parks at a time in practice, but the gate is keyed by node
id so parallel branches each park independently.
"""

from __future__ import annotations

import asyncio
from typing import Any

from xflows_engine.executors.approval import normalize_decision

DEFAULT_SIGNAL_TIMEOUT_S = 259_200  # 72h


class ApprovalGate:
    """Collects decisions sent as Temporal signals; waits with a timer."""

    def __init__(self) -> None:
        self._decisions: dict[str, dict[str, Any]] = {}

    def record(
        self,
        node_id: str,
        signal_name: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a signal decision for a node; returns the normalized decision."""
        payload = payload if isinstance(payload, dict) else {}
        decision = normalize_decision(signal_name)
        resolved = {
            "decision": decision,
            "reviewer": str(payload.get("reviewer", "")),
            "comment": str(payload.get("comment", "")),
            "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        }
        self._decisions[node_id] = resolved
        return resolved

    def has(self, node_id: str) -> bool:
        return node_id in self._decisions

    def get(self, node_id: str) -> dict[str, Any] | None:
        return self._decisions.get(node_id)

    async def wait(self, node_id: str, timeout_s: float) -> dict[str, Any]:
        """Plain-asyncio wait (unit tests); the workflow itself uses wait_condition."""
        try:
            return await asyncio.wait_for(self._wait(node_id), timeout=timeout_s)
        except asyncio.TimeoutError:
            return {"decision": "timeout", "reviewer": "", "comment": "", "evidence": {}}

    async def _wait(self, node_id: str) -> dict[str, Any]:
        while node_id not in self._decisions:
            await asyncio.sleep(0.01)
        return self._decisions[node_id]  # type: ignore[return-value]
