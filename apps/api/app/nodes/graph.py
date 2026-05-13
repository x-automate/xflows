from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


def normalize_workflow_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_nodes = [node for node in nodes if not node.get("parent")]
    node_ids = {node["id"] for node in normalized_nodes}
    normalized_edges = [
        edge
        for edge in edges
        if (edge.get("kind") or "data") == "data"
        and edge.get("source") in node_ids
        and edge.get("target") in node_ids
    ]
    return normalized_nodes, normalized_edges


def topo_sort(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    incoming = {node["id"]: 0 for node in nodes}
    adjacency: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for edge in edges:
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


@dataclass(slots=True)
class NodeGraphRunner:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    user_input: str

    def ordered_node_ids(self) -> list[str]:
        return topo_sort(self.nodes, self.edges)

    async def run(
        self,
        execute_node: Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        order = self.ordered_node_ids()
        node_by_id = {node["id"]: node for node in self.nodes}
        incoming_by_target = {edge["target"]: edge["source"] for edge in self.edges}
        outputs: dict[str, dict[str, Any]] = {}
        for node_id in order:
            node = node_by_id[node_id]
            source_node = incoming_by_target.get(node_id)
            input_payload = outputs.get(source_node, {"value": self.user_input})
            outputs[node_id] = await execute_node(node, input_payload)
        return outputs, order

    def resolve_output_node_id(self, order: list[str]) -> str:
        output_node = next((node for node in self.nodes if node.get("componentId") == "Output"), None)
        return output_node["id"] if output_node else order[-1]
