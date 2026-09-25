from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .predicates import evaluate_when


def normalize_workflow_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        parent_id = node.get("parent")
        if parent_id:
            children_by_parent.setdefault(str(parent_id), []).append(node)

    normalized_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("parent"):
            continue
        merged = dict(node)
        children = children_by_parent.get(str(node.get("id")), [])
        provider_child = children[0] if children else None
        if provider_child:
            merged["componentId"] = provider_child.get("componentId", merged.get("componentId"))
            merged["params"] = {
                **(node.get("params", {}) or {}),
                **(provider_child.get("params", {}) or {}),
            }
            merged["providerComponentId"] = provider_child.get("componentId")
        normalized_nodes.append(merged)

    node_ids = {node["id"] for node in normalized_nodes}
    normalized_edges = [
        edge
        for edge in edges
        if (edge.get("kind") or "data") in ("data", "error")
        and edge.get("source") in node_ids
        and edge.get("target") in node_ids
    ]
    return normalized_nodes, normalized_edges


def _data_like_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for edge in edges if (edge.get("kind") or "data") in ("data", "error")]


def _edge_key(edge: dict[str, Any]) -> str:
    return str(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}")


def topo_sort(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    incoming = {node["id"]: 0 for node in nodes}
    adjacency: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for edge in _data_like_edges(edges):
        source = edge.get("source")
        target = edge.get("target")
        if source not in incoming or target not in incoming:
            continue
        incoming[target] += 1
        adjacency[source].append(target)

    queue = deque(node_id for node_id, count in incoming.items() if count == 0)
    order: list[str] = []
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for next_id in adjacency[node_id]:
            incoming[next_id] -= 1
            if incoming[next_id] == 0:
                queue.append(next_id)

    if len(order) != len(nodes):
        raise ValueError("Workflow graph contains a cycle")
    return order


def execution_batches(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[list[str]]:
    incoming = {node["id"]: 0 for node in nodes}
    adjacency: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for edge in _data_like_edges(edges):
        source = edge.get("source")
        target = edge.get("target")
        if source in incoming and target in incoming:
            incoming[target] += 1
            adjacency[source].append(target)

    current = [node["id"] for node in nodes if incoming[node["id"]] == 0]
    batches: list[list[str]] = []
    scheduled = set(current)
    while current:
        batches.append(current)
        next_level: list[str] = []
        for node_id in current:
            for target in adjacency[node_id]:
                incoming[target] -= 1
                if incoming[target] == 0 and target not in scheduled:
                    scheduled.add(target)
                    next_level.append(target)
        current = next_level
    if len(scheduled) != len(nodes):
        raise ValueError("Workflow graph contains a cycle")
    return batches


def _assemble_payload(
    deliveries: list[tuple[int, dict[str, Any] | None, dict[str, Any]]],
) -> dict[str, Any]:
    payloads = [payload for _, _, payload in deliveries]
    if len(payloads) == 1:
        return payloads[0]
    branches: dict[str, Any] = {}
    for _, edge, payload in deliveries:
        key = _edge_key(edge) if edge else "root"
        branches[key] = payload
    return {
        "value": payloads[0].get("value", ""),
        "branches": branches,
        "items": payloads,
    }


@dataclass(slots=True)
class NodeGraphRunner:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    user_input: str

    def ordered_node_ids(self) -> list[str]:
        return topo_sort(self.nodes, self.edges)

    def batches(self) -> list[list[str]]:
        return execution_batches(self.nodes, self.edges)

    async def run(
        self,
        execute_node: Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, str]]:
        order = topo_sort(self.nodes, self.edges)
        node_by_id = {node["id"]: node for node in self.nodes}
        edge_list = [
            edge
            for edge in _data_like_edges(self.edges)
            if edge.get("source") in node_by_id and edge.get("target") in node_by_id
        ]
        edge_index = {key: idx for idx, key in enumerate(_edge_key(edge) for edge in edge_list)}
        out_edges_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        incoming_count: dict[str, int] = defaultdict(int)
        for edge in edge_list:
            out_edges_by_source[edge["source"]].append(edge)
            incoming_count[edge["target"]] += 1

        outputs: dict[str, dict[str, Any]] = {}
        statuses: dict[str, str] = {}
        pending: dict[str, list[tuple[int, dict[str, Any] | None, dict[str, Any]]]] = defaultdict(list)
        failure: BaseException | None = None

        def push(edge: dict[str, Any], payload: dict[str, Any]) -> None:
            pending[edge["target"]].append((edge_index.get(_edge_key(edge), 0), edge, payload))

        def deliver_data(source_id: str, payload: dict[str, Any]) -> None:
            for edge in out_edges_by_source.get(source_id, []):
                if (edge.get("kind") or "data") == "error":
                    continue
                when = edge.get("when")
                if when is not None and str(when).strip() != "" and not evaluate_when(when, payload):
                    continue
                push(edge, payload)

        def deliver_error(source_id: str, error: BaseException) -> None:
            payload = {
                "value": "",
                "error": {
                    "message": str(error) or type(error).__name__,
                    "nodeId": source_id,
                    "componentId": str(node_by_id[source_id].get("componentId") or ""),
                },
            }
            for edge in out_edges_by_source.get(source_id, []):
                if (edge.get("kind") or "data") == "error":
                    push(edge, payload)

        async def run_node(node_id: str) -> None:
            nonlocal failure
            node = node_by_id[node_id]
            deliveries = pending.pop(node_id, [])
            if not deliveries:
                if incoming_count.get(node_id, 0) > 0:
                    statuses[node_id] = "skipped"
                    return
                deliveries = [(0, None, {"value": self.user_input})]
            deliveries.sort(key=lambda item: item[0])
            input_payload = _assemble_payload(deliveries)
            try:
                result = await execute_node(node, input_payload)
            except Exception as exc:
                has_error_edge = any(
                    (edge.get("kind") or "data") == "error"
                    for edge in out_edges_by_source.get(node_id, [])
                )
                if has_error_edge:
                    statuses[node_id] = "failed_routed"
                    deliver_error(node_id, exc)
                elif str(node.get("onError") or "").lower() == "continue":
                    fallback = {
                        "value": input_payload.get("value", ""),
                        "nodeError": str(exc) or type(exc).__name__,
                    }
                    outputs[node_id] = fallback
                    statuses[node_id] = "failed_continued"
                    deliver_data(node_id, fallback)
                else:
                    statuses[node_id] = "failed"
                    if failure is None:
                        failure = exc
                return
            outputs[node_id] = result
            statuses[node_id] = "succeeded"
            deliver_data(node_id, result)

        for batch in execution_batches(self.nodes, edge_list):
            await asyncio.gather(*(run_node(node_id) for node_id in batch))
            if failure is not None:
                raise failure

        return outputs, order, statuses

    def resolve_output_node_id(self, order: list[str]) -> str:
        output_node = next((node for node in self.nodes if node.get("componentId") == "Output"), None)
        if output_node:
            return output_node["id"]
        if not order:
            # An empty graph used to surface as a bare "list index out of range"
            # in the run record; say what actually went wrong instead.
            raise ValueError("Workflow has no nodes to execute; add an Input and an Output node")
        return order[-1]
