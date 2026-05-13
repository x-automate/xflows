import { useMemo } from "react";
import { getComponentMeta } from "../catalog/catalog-meta";

const meta = (node) =>
  getComponentMeta(node.componentId) || {
    name: "?",
    kind: "transform",
    params: [],
  };

export function topoSort(nodes, edges) {
  const incoming = Object.fromEntries(nodes.map((node) => [node.id, 0]));
  const adjacency = Object.fromEntries(nodes.map((node) => [node.id, []]));

  for (const edge of edges) {
    incoming[edge.target] = (incoming[edge.target] || 0) + 1;
    adjacency[edge.source].push(edge.target);
  }

  const queue = nodes.filter((node) => incoming[node.id] === 0).map((node) => node.id);
  const order = [];

  while (queue.length) {
    const nodeId = queue.shift();
    order.push(nodeId);
    for (const nextId of adjacency[nodeId]) {
      incoming[nextId] -= 1;
      if (incoming[nextId] === 0) {
        queue.push(nextId);
      }
    }
  }

  return order.length === nodes.length ? order : null;
}

export function validateWorkflow(nodes, edges) {
  const errors = [];
  if (nodes.length === 0) {
    errors.push("Canvas is empty — drop a node to get started.");
    return { errors, order: [] };
  }

  const nodeById = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const dataEdges = edges.filter((edge) => (edge.kind || "data") === "data");
  const configEdges = edges.filter((edge) => edge.kind === "config");
  const order = topoSort(nodes, dataEdges);
  if (!order) {
    errors.push("Workflow contains a cycle. Remove the looping connection.");
    return { errors, order: [] };
  }

  const outDeg = Object.fromEntries(nodes.map((node) => [node.id, 0]));
  const inDeg = Object.fromEntries(nodes.map((node) => [node.id, 0]));
  dataEdges.forEach((edge) => {
    outDeg[edge.source] += 1;
    inDeg[edge.target] += 1;
  });

  const inputs = nodes.filter((node) => meta(node).kind === "input");
  const outputs = nodes.filter((node) => meta(node).kind === "output");
  if (inputs.length === 0) errors.push("Workflow needs an Input node (entry point).");
  if (inputs.length > 1) errors.push("Workflow has multiple Input nodes — only one entry point allowed.");
  if (outputs.length === 0) errors.push("Workflow needs an Output node (final step).");
  if (outputs.length > 1) errors.push("Workflow has multiple Output nodes — only one terminal allowed.");

  const configInDeg = Object.fromEntries(nodes.map((node) => [node.id, 0]));
  const configOutDeg = Object.fromEntries(nodes.map((node) => [node.id, 0]));
  configEdges.forEach((edge) => {
    configOutDeg[edge.source] += 1;
    configInDeg[edge.target] += 1;
  });

  if (nodes.length > 1) {
    nodes.forEach((node) => {
      const nodeMeta = meta(node);
      if (node.parent) return;
      if (nodeMeta.kind === "provider") return;
      if (
        outDeg[node.id] === 0 &&
        inDeg[node.id] === 0 &&
        configInDeg[node.id] === 0 &&
        configOutDeg[node.id] === 0
      ) {
        errors.push(`"${meta(node).name}" is not connected.`);
      }
    });
  }
  outputs.forEach((outputNode) => {
    if (outDeg[outputNode.id] > 0) {
      errors.push(`Output "${meta(outputNode).name}" must be terminal.`);
    }
  });
  inputs.forEach((inputNode) => {
    if (inDeg[inputNode.id] > 0) {
      errors.push(`Input "${meta(inputNode).name}" cannot have incoming edges.`);
    }
  });

  nodes.forEach((node) => {
    const nodeMeta = meta(node);
    if (nodeMeta.kind === "provider") {
      const parent = node.parent ? nodeById[node.parent] : null;
      const parentMeta = parent ? meta(parent) : null;
      if (!parent || !parentMeta || parentMeta.kind !== "container") {
        errors.push(`"${nodeMeta.name}" must be placed inside a container.`);
      } else if (
        Array.isArray(parentMeta.accepts) &&
        !parentMeta.accepts.includes(nodeMeta.category)
      ) {
        errors.push(
          `"${nodeMeta.name}" is not accepted by "${parentMeta.name}".`
        );
      }
    }
    if (nodeMeta.kind === "container") {
      const children = nodes.filter((item) => item.parent === node.id);
      if (children.length > 1) {
        errors.push(`"${nodeMeta.name}" can only contain one provider.`);
      }
    }
  });

  configEdges.forEach((edge) => {
    const source = nodeById[edge.source];
    const target = nodeById[edge.target];
    if (!source || !target) {
      errors.push("Config edge references a missing node.");
      return;
    }
    const sourceMeta = meta(source);
    const targetMeta = meta(target);
    const configs = targetMeta.configs || [];
    const slot = configs.find((item) => item.name === edge.slot);
    if (!slot) {
      errors.push(
        `Invalid config slot "${edge.slot || "?"}" on "${targetMeta.name}".`
      );
      return;
    }
    if (
      Array.isArray(slot.accepts) &&
      slot.accepts.length > 0 &&
      !slot.accepts.includes(sourceMeta.category)
    ) {
      errors.push(
        `"${sourceMeta.name}" cannot connect to "${targetMeta.name}.${slot.name}".`
      );
    }
  });

  return { errors, order };
}

export function useWorkflowValidation(nodes, edges) {
  return useMemo(() => validateWorkflow(nodes, edges), [nodes, edges]);
}
