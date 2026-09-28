import { getComponentMeta } from "./catalog-meta.js";
import { hasDataIn, hasDataOut, hasErrorOut, isAuxOnly } from "./port-model.js";

export { isAuxOnly };

/**
 * Connection rules for the canvas.
 *
 * Until now `connect()` accepted any source/target pair and the graph was only
 * judged afterwards by `validateWorkflow`. That let the editor draw edges the
 * engine silently drops (config edges) or that can never carry data (an edge
 * into an Input, a data edge out of an Output), and it made a mis-grabbed
 * error port look like a broken data wire instead of a rejected one.
 *
 * `checkConnection` is the single gate the canvas asks before an edge exists.
 */

function metaOf(node) {
  return node ? getComponentMeta(node.componentId) : null;
}

function reachable(edges, fromId, toId) {
  const adjacency = new Map();
  for (const edge of edges) {
    if ((edge.kind || "data") === "config") continue;
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, []);
    adjacency.get(edge.source).push(edge.target);
  }
  const seen = new Set([fromId]);
  const queue = [fromId];
  while (queue.length) {
    const current = queue.shift();
    if (current === toId) return true;
    for (const next of adjacency.get(current) || []) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return false;
}

/**
 * @returns {{ok: true} | {ok: false, reason: string}}
 */
export function checkConnection({ nodes, edges, source, target, kind = "data", slot }) {
  const sourceNode = nodes.find((node) => node.id === source);
  const targetNode = nodes.find((node) => node.id === target);
  const sourceMeta = metaOf(sourceNode);
  const targetMeta = metaOf(targetNode);

  if (!sourceNode || !targetNode) {
    return { ok: false, reason: "Connection references a node that no longer exists." };
  }
  if (source === target) {
    return { ok: false, reason: "A node cannot connect to itself." };
  }
  if (!sourceMeta || !targetMeta) {
    return { ok: false, reason: "Unknown component — cannot validate this connection." };
  }
  if (sourceNode.parent || targetNode.parent) {
    return {
      ok: false,
      reason: "Provider nodes are wired through their container, not directly.",
    };
  }

  const duplicate = edges.some(
    (edge) =>
      edge.source === source &&
      edge.target === target &&
      (edge.kind || "data") === kind &&
      (edge.slot ?? undefined) === (slot ?? undefined)
  );
  if (duplicate) {
    return { ok: false, reason: `${sourceMeta.name} → ${targetMeta.name} is already connected.` };
  }

  if (kind === "config") {
    const slots = targetMeta.configs || [];
    const targetSlot = slots.find((item) => item.name === slot);
    if (!targetSlot) {
      return { ok: false, reason: `"${targetMeta.name}" has no "${slot || "?"}" slot.` };
    }
    if (
      Array.isArray(targetSlot.accepts) &&
      targetSlot.accepts.length > 0 &&
      !targetSlot.accepts.includes(sourceMeta.category)
    ) {
      return {
        ok: false,
        reason: `${targetSlot.label || targetSlot.name} accepts ${targetSlot.accepts.join(
          " or "
        )} — ${sourceMeta.name} is ${sourceMeta.category}.`,
      };
    }
    return { ok: true };
  }

  // Data and error edges share one topology, read off the same port model the
  // canvas draws: an edge may only start where its source shows an output
  // bubble and land where its target shows an input bubble. The one asymmetry
  // is the terminal Output — it produces no data, but it still executes and so
  // can still fail, which is why it carries an error output and nothing else.
  if (isAuxOnly(sourceMeta) || isAuxOnly(targetMeta)) {
    const auxName = isAuxOnly(sourceMeta) ? sourceMeta.name : targetMeta.name;
    return {
      ok: false,
      reason: `"${auxName}" attaches to a config slot, not to the data flow.`,
    };
  }
  if (!hasDataIn(targetMeta)) {
    return { ok: false, reason: `"${targetMeta.name}" is an entry point and takes no input.` };
  }
  if (kind === "error" ? !hasErrorOut(sourceMeta) : !hasDataOut(sourceMeta)) {
    return {
      ok: false,
      reason: `"${sourceMeta.name}" is terminal and produces no data output.`,
    };
  }
  if (reachable(edges, target, source)) {
    return {
      ok: false,
      reason: `${sourceMeta.name} → ${targetMeta.name} would create a loop.`,
    };
  }

  return { ok: true };
}

export default checkConnection;
