import { XFLOWS_CATALOG, getComponentMeta, isPlaceable } from "./catalog-meta.js";
import { checkConnection } from "./connection-rules.js";

/**
 * What a dangling wire can legally be joined to.
 *
 * Dropping a wire on empty canvas opens a menu instead of throwing the wire
 * away, and the menu must never offer a connection the canvas would then
 * refuse. So every row here is produced by running the real `checkConnection`
 * gate — once against the nodes already on the canvas, and once against a
 * probe node standing in for each component the menu could create.
 *
 * A pending wire is described by the bubble it was started from:
 *   { anchorId, direction: "forward" | "reverse", kind, slot }
 * "forward" means the drag began on an output, so the anchor is the edge's
 * source; "reverse" means it began on an input and the anchor is its target.
 */

const PROBE_ID = "__connect_probe__";

/** Which way round the edge runs, given which end the user is holding. */
export function linkFor(pending, otherId, slot) {
  const { anchorId, direction, kind = "data" } = pending;
  return direction === "reverse"
    ? { source: otherId, target: anchorId, kind, slot }
    : { source: anchorId, target: otherId, kind, slot };
}

/**
 * Config edges name a slot on their target. When the user holds the source end
 * the slot is still open, so every slot on the other node is a separate offer;
 * when they hold the target end the slot is already decided.
 */
function slotOptions(pending, otherMeta) {
  if ((pending.kind || "data") !== "config") return [undefined];
  if (pending.direction === "reverse") return [pending.slot];
  return (otherMeta?.configs || []).map((slot) => slot.name);
}

/**
 * Each slot the wire could legally take on this node. A data or error edge has
 * exactly one option (no slot); a config edge offers every slot that accepts
 * the source, so a three-slot container shows up as three rows to choose from.
 */
function legalSlots({ nodes, edges, pending, otherId, otherMeta }) {
  return slotOptions(pending, otherMeta).filter(
    (slot) => checkConnection({ nodes, edges, ...linkFor(pending, otherId, slot) }).ok
  );
}

/**
 * Rows for the nodes already on the canvas, and rows for the components the
 * menu could drop in and wire up in one go.
 */
export function connectCandidates({ nodes = [], edges = [], pending }) {
  if (!pending?.anchorId) return { onCanvas: [], create: [] };

  const onCanvas = [];
  for (const node of nodes) {
    if (node.id === pending.anchorId || node.parent) continue;
    const meta = getComponentMeta(node.componentId);
    if (!meta) continue;
    for (const slot of legalSlots({ nodes, edges, pending, otherId: node.id, otherMeta: meta })) {
      onCanvas.push({
        type: "node",
        key: `node:${node.id}:${slot || ""}`,
        id: node.id,
        componentId: meta.id,
        name: meta.name,
        category: meta.category,
        desc: meta.desc,
        icon: meta.icon,
        slot,
      });
    }
  }

  const create = [];
  for (const component of XFLOWS_CATALOG) {
    // A provider is only ever valid inside a container, and a planned
    // component cannot run — neither belongs in a one-click "add and wire".
    if (!isPlaceable(component) || component.kind === "provider") continue;
    const probe = { id: PROBE_ID, componentId: component.id, x: 0, y: 0, params: {} };
    const slots = legalSlots({
      nodes: [...nodes, probe],
      edges,
      pending,
      otherId: PROBE_ID,
      otherMeta: component,
    });
    for (const slot of slots) {
      create.push({
        type: "component",
        key: `component:${component.id}:${slot || ""}`,
        componentId: component.id,
        name: component.name,
        category: component.category,
        desc: component.desc,
        icon: component.icon,
        slot,
      });
    }
  }

  return { onCanvas, create };
}

/** Rows whose name, component id, category or description contain `query`. */
export function filterCandidates(rows, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) =>
    [row.name, row.componentId, row.category, row.desc].some((field) =>
      String(field || "").toLowerCase().includes(needle)
    )
  );
}
