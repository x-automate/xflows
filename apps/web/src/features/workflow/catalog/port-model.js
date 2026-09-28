import { canSourceConfigEdge, getComponentMeta } from "./catalog-meta.js";

/**
 * The port model: which bubbles a node shows, and exactly where each one sits.
 *
 * Canvas.jsx used to hold these numbers inline and workflow.css held a second
 * copy of the same offsets. The two drifted — a `.wf-port` block declared after
 * `.wf-port-error-out` quietly won the cascade, so every error bubble rendered
 * underneath its data bubble while the error edge was still drawn 20px lower.
 * Positions now live here only: the canvas places each bubble at the point this
 * module returns and draws every edge endpoint from the same function, so a
 * wire cannot miss the port it claims to leave.
 */

export const NODE_W = 132;
// Tall enough for two stacked output bubbles to sit inside the node's own
// height: the error bubble drops ERROR_PORT_DROP below centre and must not
// hang off the bottom edge.
export const NODE_H = 56;
export const CONT_W = 200;
export const CONT_H = 110;

/** Vertical drop of the error bubble below the data bubble. */
export const ERROR_PORT_DROP = 18;

export const PORT_IN = "in";
export const PORT_DATA_OUT = "out";
export const PORT_ERROR_OUT = "error-out";
export const PORT_CONFIG_OUT = "config-out";
export const PORT_CONFIG_IN = "config-in";

export function sizeFor(meta) {
  if (meta?.kind === "container") return { w: CONT_W, h: CONT_H };
  return { w: NODE_W, h: NODE_H };
}

/**
 * Aux nodes attach to a container's config slot instead of the data flow, so
 * they carry a config bubble rather than data/error bubbles. Everything else
 * executes, and everything that executes can fail.
 *
 * This is `kind === "aux"`, never a category: `TraceLog` and `ErrorLog` are
 * categorised Observability but are ordinary inline transforms with real data
 * ports, and gating on the category stripped them.
 */
export function isAuxOnly(meta) {
  return meta?.kind === "aux";
}

const isAux = isAuxOnly;

export function hasDataIn(meta) {
  return Boolean(meta) && !isAux(meta) && meta.kind !== "input";
}

/** A terminal Output is a sink: it produces nothing downstream. */
export function hasDataOut(meta) {
  return Boolean(meta) && !isAux(meta) && meta.kind !== "output";
}

/** Every executing node gets one, triggers and the terminal Output included. */
export function hasErrorOut(meta) {
  return Boolean(meta) && !isAux(meta);
}

export function hasConfigOut(meta) {
  return canSourceConfigEdge(meta);
}

export function configSlotsOf(meta) {
  return meta?.configs || [];
}

const metaFor = (node, meta) => meta ?? getComponentMeta(node?.componentId);

/** Bubble centres, in canvas coordinates. Each sits on the node's own edge. */
export function dataPortPos(node, side, meta) {
  const size = sizeFor(metaFor(node, meta));
  return {
    x: side === "in" ? node.x : node.x + size.w,
    y: node.y + size.h / 2,
  };
}

export function errorOutPortPos(node, meta) {
  const size = sizeFor(metaFor(node, meta));
  return { x: node.x + size.w, y: node.y + size.h / 2 + ERROR_PORT_DROP };
}

export function configOutPortPos(node, meta) {
  const size = sizeFor(metaFor(node, meta));
  return { x: node.x + size.w / 2, y: node.y };
}

export function configInPortPos(node, slotIdx, totalSlots, meta) {
  const size = sizeFor(metaFor(node, meta));
  const step = size.w / ((totalSlots || 1) + 1);
  return { x: node.x + step * (slotIdx + 1), y: node.y + size.h };
}

/** Where an edge of `kind` leaves its source node. */
export function sourcePortPos(node, kind, meta) {
  if (kind === "config") return configOutPortPos(node, meta);
  if (kind === "error") return errorOutPortPos(node, meta);
  return dataPortPos(node, "out", meta);
}

/** Where an edge of `kind` lands on its target node. */
export function targetPortPos(node, kind, slot, meta) {
  const resolved = metaFor(node, meta);
  if (kind !== "config") return dataPortPos(node, "in", resolved);
  const slots = configSlotsOf(resolved);
  const idx = Math.max(
    0,
    slots.findIndex((item) => item.name === slot)
  );
  return configInPortPos(node, idx, slots.length, resolved);
}

/**
 * Every bubble a node renders, positioned. The canvas maps straight over this,
 * so "does this node show both outputs?" is answerable without a browser.
 */
export function portsForNode(node, meta) {
  const resolved = metaFor(node, meta);
  if (!resolved) return [];
  const ports = [];

  if (hasDataIn(resolved)) {
    ports.push({
      key: `${node.id}:${PORT_IN}`,
      port: PORT_IN,
      className: "wf-port-in",
      title: "Data input",
      ...dataPortPos(node, "in", resolved),
    });
  }
  if (hasDataOut(resolved)) {
    ports.push({
      key: `${node.id}:${PORT_DATA_OUT}`,
      port: PORT_DATA_OUT,
      wireKind: "data",
      className: "wf-port-out",
      title: "Data output — the normal result of this node",
      ...dataPortPos(node, "out", resolved),
    });
  }
  if (hasErrorOut(resolved)) {
    ports.push({
      key: `${node.id}:${PORT_ERROR_OUT}`,
      port: PORT_ERROR_OUT,
      wireKind: "error",
      className: "wf-port-error-out",
      title: "Error output — runs instead when this node fails",
      ...errorOutPortPos(node, resolved),
    });
  }
  if (hasConfigOut(resolved)) {
    ports.push({
      key: `${node.id}:${PORT_CONFIG_OUT}`,
      port: PORT_CONFIG_OUT,
      wireKind: "config",
      className: "wf-port-config-out",
      title: `Config output — attach ${resolved.name} to a container slot`,
      ...configOutPortPos(node, resolved),
    });
  }
  const slots = configSlotsOf(resolved);
  slots.forEach((slot, idx) => {
    ports.push({
      key: `${node.id}:${PORT_CONFIG_IN}:${slot.name}`,
      port: PORT_CONFIG_IN,
      slot: slot.name,
      label: slot.label || slot.name,
      className: "wf-port-config-in",
      title: `${slot.label || slot.name} (accepts ${(slot.accepts || []).join(", ")})`,
      ...configInPortPos(node, idx, slots.length, resolved),
    });
  });

  return ports;
}
