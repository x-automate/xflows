from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..predicates import resolve_path
from ..result import NodeExecutionResult


def _parse_routes(raw: Any) -> list[dict[str, Any]]:
    if raw is None or str(raw).strip() == "":
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as error:
        raise ValueError(f"Switch routes must be valid JSON: {error}") from error
    if not isinstance(parsed, list):
        raise ValueError("Switch routes must be a JSON array of rule objects")
    return [item for item in parsed if isinstance(item, dict)]


def _match_route(rules: list[dict[str, Any]], value: Any) -> str | None:
    text = str(value)
    for rule in rules:
        name = str(rule.get("name") or "")
        comparator = str(rule.get("match") or rule.get("comparator") or "contains")
        pattern = rule.get("pattern", rule.get("contains", rule.get("equals", "")))
        if comparator == "equals":
            if str(pattern) == text:
                return name
        elif comparator == "regex":
            try:
                if re.search(str(pattern), text):
                    return name
            except re.error as error:
                raise ValueError(f"Switch rule '{name}' has invalid regex: {error}") from error
        else:
            if str(pattern) in text:
                return name
    return None


class SwitchExecutor(BaseNodeExecutor):
    component_ids = ("Switch",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        rules = _parse_routes(params.get("routes"))
        field = str(params.get("field", "value"))
        value = resolve_path(input_payload, field)
        matched = _match_route(rules, value)
        return NodeExecutionResult(
            value=value if value is not None else input_payload.get("value", ""),
            metadata={"switch": {"route": matched or "", "matched": matched is not None}},
        )


class IfElseExecutor(BaseNodeExecutor):
    component_ids = ("IfElse",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        needle = str(params.get("contains", ""))
        mode = str(params.get("mode", "warn")).lower()
        value = str(input_payload.get("value", ""))
        matched = needle in value if needle else True
        if mode == "fail" and not matched:
            raise ValueError(f"IfElse: value does not contain '{needle}'")
        return NodeExecutionResult(
            value=value,
            metadata={"ifelse": {"matched": matched, "mode": mode, "contains": needle}},
        )


class WaitExecutor(BaseNodeExecutor):
    component_ids = ("Wait",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        try:
            seconds = float(params.get("seconds", 1))
        except (TypeError, ValueError) as error:
            raise ValueError("Wait requires a numeric 'seconds' parameter") from error
        seconds = max(0.0, min(seconds, 3600.0))
        await asyncio.sleep(seconds)
        return NodeExecutionResult(
            value=input_payload.get("value", ""),
            metadata={"waitedSeconds": seconds},
        )


class LoudFailureExecutor(BaseNodeExecutor):
    component_ids = ()

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        component_id = str(node.get("componentId") or "unknown")
        raise ValueError(
            f"Component '{component_id}' has no registered executor and cannot execute "
            "(inert components fail loudly; see XF-02)"
        )
