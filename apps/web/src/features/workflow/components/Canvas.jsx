import { useEffect, useMemo, useRef, useState } from "react";
import {
  CATEGORY_COLORS,
  XFLOWS_ICONS,
  getComponentMeta,
} from "../catalog/catalog-meta";
import {
  NODE_H,
  NODE_W,
  nodeOriginForPort,
  portsForNode,
  sizeFor,
  sourcePortPos,
  targetPortPos,
} from "../catalog/port-model";
import { linkFor } from "../catalog/connect-candidates";
import ConnectMenu from "./ConnectMenu";

/**
 * Which bubble the far end of a wire has to land on, given which end is held.
 * Holding an output looks for an input; holding an input looks for an output,
 * and a red one there turns the wire into an error edge.
 */
const DROP_SELECTOR = {
  "forward:data": "[data-port='in']",
  "forward:error": "[data-port='in']",
  "forward:config": "[data-port='config-in']",
  "reverse:data": "[data-port='out'],[data-port='error-out']",
  "reverse:error": "[data-port='out'],[data-port='error-out']",
  "reverse:config": "[data-port='config-out']",
};

/** The bubble a newly created node must present to the wire that made it. */
const NEW_NODE_PORT = {
  "forward:data": "in",
  "forward:error": "in",
  "forward:config": "config-in",
  "reverse:data": "out",
  "reverse:error": "out",
  "reverse:config": "config-out",
};

const wireKey = (wire) => `${wire.direction}:${wire.kind || "data"}`;

function Canvas({
  nodes,
  edges,
  selected,
  onSelect,
  onNodeMove,
  onNodeAdd,
  onConnect,
  onConnectNew,
  onDelete,
  onOpenParams,
  onUpdateEdge,
  onDeleteEdge,
}) {
  const wrapRef = useRef(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [drag, setDrag] = useState(null);
  const [pendingWire, setPendingWire] = useState(null);
  const [connectMenu, setConnectMenu] = useState(null);

  const nodeById = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.id, node])),
    [nodes]
  );
  const metaOf = (node) => getComponentMeta(node.componentId);
  const topLevelNodes = nodes.filter((node) => !node.parent);

  const onWheel = (event) => {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      const rect = wrapRef.current.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const my = event.clientY - rect.top;
      const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
      const k2 = Math.max(0.4, Math.min(2, view.k * factor));
      const x2 = mx - ((mx - view.x) * k2) / view.k;
      const y2 = my - ((my - view.y) * k2) / view.k;
      setView({ x: x2, y: y2, k: k2 });
    } else {
      setView((current) => ({
        ...current,
        x: current.x - event.deltaX,
        y: current.y - event.deltaY,
      }));
    }
  };

  /**
   * Ports render in their own layer above the nodes, so a pointer over a
   * bubble no longer sits inside the node element. Fall back to the bubble's
   * owner so dropping a provider on a container's edge still lands in it.
   */
  const containerIdAt = (el) => {
    const containerEl = el?.closest?.("[data-container-id]");
    if (containerEl) return containerEl.dataset.containerId;
    const portEl = el?.closest?.("[data-port]");
    const owner = portEl ? nodeById[portEl.dataset.nodeId] : null;
    return owner && metaOf(owner)?.kind === "container" ? owner.id : null;
  };

  const onDrop = (event) => {
    event.preventDefault();
    const componentId = event.dataTransfer.getData("component-id");
    if (!componentId) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const x = (event.clientX - rect.left - view.x) / view.k - NODE_W / 2;
    const y = (event.clientY - rect.top - view.y) / view.k - NODE_H / 2;
    const el = document.elementFromPoint(event.clientX, event.clientY);
    onNodeAdd(componentId, { x, y }, containerIdAt(el));
  };

  const onMouseDown = (event) => {
    if (event.target === wrapRef.current || event.target.dataset.bg === "1") {
      setDrag({
        type: "pan",
        sx: event.clientX,
        sy: event.clientY,
        vx: view.x,
        vy: view.y,
      });
      onSelect(null);
    }
  };

  const onMouseMove = (event) => {
    if (!drag && !pendingWire) return;
    const rect = wrapRef.current.getBoundingClientRect();
    if (drag?.type === "pan") {
      setView((current) => ({
        ...current,
        x: drag.vx + (event.clientX - drag.sx),
        y: drag.vy + (event.clientY - drag.sy),
      }));
    } else if (drag?.type === "node") {
      const x = (event.clientX - rect.left - view.x) / view.k - drag.ox;
      const y = (event.clientY - rect.top - view.y) / view.k - drag.oy;
      onNodeMove(drag.id, { x, y });
    } else if (pendingWire) {
      const x = (event.clientX - rect.left - view.x) / view.k;
      const y = (event.clientY - rect.top - view.y) / view.k;
      setPendingWire({ ...pendingWire, tx: x, ty: y });
    }
  };

  /**
   * Where a released wire lands: the bubble under the cursor, or failing that
   * the node under it, so a drop anywhere on a node still connects.
   */
  const resolveDrop = (el, wire) => {
    const portEl = el?.closest?.(DROP_SELECTOR[wireKey(wire)] || "[data-port='in']");
    if (portEl && portEl.dataset.nodeId !== wire.anchorId) {
      const droppedOnError =
        wire.direction === "reverse" && portEl.dataset.port === "error-out";
      return {
        otherId: portEl.dataset.nodeId,
        kind: droppedOnError ? "error" : wire.kind,
        slot:
          wire.kind === "config"
            ? wire.direction === "reverse"
              ? wire.slot
              : portEl.dataset.slot
            : undefined,
      };
    }
    const otherId = el?.closest?.("[data-node-id]")?.dataset?.nodeId;
    if (!otherId || otherId === wire.anchorId) return null;
    if (wire.kind === "config" && wire.direction === "forward") {
      // Which slot is not obvious from the node body; let the menu ask.
      const slots = metaOf(nodeById[otherId])?.configs || [];
      if (slots.length !== 1) return null;
      return { otherId, kind: "config", slot: slots[0].name };
    }
    return { otherId, kind: wire.kind, slot: wire.slot };
  };

  const onMouseUp = (event) => {
    setDrag(null);
    if (!pendingWire) return;
    const wire = pendingWire;
    setPendingWire(null);
    const el = document.elementFromPoint(event.clientX, event.clientY);
    const landed = resolveDrop(el, wire);
    if (landed) {
      const link = linkFor(
        { ...wire, kind: landed.kind },
        landed.otherId,
        landed.slot
      );
      onConnect(link.source, link.target, link.kind, link.slot);
      return;
    }
    const pulled = Math.hypot(event.clientX - wire.cx, event.clientY - wire.cy) >= 4;
    if (!pulled) return;
    // Dropped on empty canvas: keep the wire on screen and ask where it goes.
    const rect = wrapRef.current.getBoundingClientRect();
    setConnectMenu({
      wire,
      at: { x: event.clientX - rect.left, y: event.clientY - rect.top },
      canvas: { x: wire.tx, y: wire.ty },
      bounds: { w: rect.width, h: rect.height },
    });
  };

  const closeConnectMenu = () => setConnectMenu(null);

  const chooseConnection = (row) => {
    const { wire, canvas } = connectMenu;
    setConnectMenu(null);
    if (row.type === "node") {
      const link = linkFor(wire, row.id, row.slot);
      onConnect(link.source, link.target, link.kind, link.slot);
      return;
    }
    const meta = getComponentMeta(row.componentId);
    const origin = nodeOriginForPort(canvas, meta, NEW_NODE_PORT[wireKey(wire)]);
    onConnectNew?.(row.componentId, origin, {
      anchorId: wire.anchorId,
      direction: wire.direction,
      kind: wire.kind,
      slot: row.slot ?? wire.slot,
    });
  };

  useEffect(() => {
    const stop = () => {
      setDrag(null);
      setPendingWire(null);
    };
    window.addEventListener("mouseup", stop);
    return () => window.removeEventListener("mouseup", stop);
  }, []);

  useEffect(() => {
    if (!connectMenu) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") setConnectMenu(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [connectMenu]);

  const edgePath = (a, b, vertical = false) => {
    if (vertical) {
      const dy = Math.max(30, Math.abs(b.y - a.y) * 0.5);
      const direction = b.y >= a.y ? 1 : -1;
      return `M ${a.x} ${a.y} C ${a.x} ${a.y + dy * direction}, ${b.x} ${b.y - dy * direction}, ${b.x} ${b.y}`;
    }
    const dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
    return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  };

  // While the menu is open the wire stays on screen, frozen where it was
  // dropped, so the choice still reads as "this wire goes to …".
  const liveWire = pendingWire || connectMenu?.wire || null;

  const beginNodeDrag = (event, node) => {
    event.stopPropagation();
    onSelect(node.id);
    const rect = wrapRef.current.getBoundingClientRect();
    const ox = (event.clientX - rect.left - view.x) / view.k - node.x;
    const oy = (event.clientY - rect.top - view.y) / view.k - node.y;
    setDrag({ type: "node", id: node.id, ox, oy });
  };

  const startWire = (event, node, port) => {
    event.stopPropagation();
    event.preventDefault();
    setConnectMenu(null);
    setPendingWire({
      anchorId: node.id,
      direction: port.direction,
      kind: port.wireKind,
      slot: port.slot,
      sx: port.x,
      sy: port.y,
      tx: port.x,
      ty: port.y,
      // Where the pointer went down, so a stray click on a bubble does not
      // pop the connect menu; only a wire someone actually pulled does.
      cx: event.clientX,
      cy: event.clientY,
    });
  };

  return (
    <div
      ref={wrapRef}
      data-bg="1"
      className="wf-canvas-wrap"
      onWheel={onWheel}
      onDragOver={(event) => event.preventDefault()}
      onDrop={onDrop}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
    >
      <div
        className="wf-canvas-grid"
        style={{
          backgroundPosition: `${view.x}px ${view.y}px`,
          backgroundSize: `${24 * view.k}px ${24 * view.k}px`,
        }}
        data-bg="1"
      />

      <div
        className="wf-canvas-inner"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}
      >
        <svg className="wf-edges" width="6000" height="6000">
          <defs>
            <marker id="wf-arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
              <path d="M 0 0 L 8 5 L 0 10 z" fill="#111" />
            </marker>
            <marker id="wf-arrow-config" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
              <path d="M 0 0 L 8 5 L 0 10 z" fill="#c2410c" />
            </marker>
            <marker id="wf-arrow-error" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
              <path d="M 0 0 L 8 5 L 0 10 z" fill="#dc2626" />
            </marker>
          </defs>
          {edges.map((edge) => {
            const sourceNode = nodeById[edge.source];
            const targetNode = nodeById[edge.target];
            if (!sourceNode || !targetNode) return null;
            const kind = edge.kind || "data";
            const isConfig = kind === "config";
            const isError = kind === "error";
            // Same functions the port bubbles are placed with, so an endpoint
            // is always the centre of the bubble it belongs to.
            const sourcePort = sourcePortPos(sourceNode, kind, metaOf(sourceNode));
            const targetPort = targetPortPos(
              targetNode,
              kind,
              edge.slot,
              metaOf(targetNode)
            );
            return (
              <g key={edge.id}>
                <path
                  d={edgePath(sourcePort, targetPort, isConfig)}
                  className={`wf-edge${isConfig ? " config" : ""}${isError ? " error" : ""}${
                    selected === edge.id ? " selected" : ""
                  }${edge.activeEdge ? " active" : ""}`}
                  fill="none"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(edge.id);
                  }}
                  markerEnd={isConfig ? "url(#wf-arrow-config)" : isError ? "url(#wf-arrow-error)" : "url(#wf-arrow)"}
                />
                {edge.activeEdge && (
                  <path
                    d={edgePath(sourcePort, targetPort, isConfig)}
                    className="wf-edge-flow"
                    fill="none"
                  />
                )}
              </g>
            );
          })}
          {liveWire && (
            <path
              d={edgePath(
                liveWire.direction === "reverse"
                  ? { x: liveWire.tx, y: liveWire.ty }
                  : { x: liveWire.sx, y: liveWire.sy },
                liveWire.direction === "reverse"
                  ? { x: liveWire.sx, y: liveWire.sy }
                  : { x: liveWire.tx, y: liveWire.ty },
                liveWire.kind === "config"
              )}
              className={`wf-wire-pending${connectMenu ? " held" : ""}`}
              data-kind={liveWire.kind}
              fill="none"
              stroke={
                liveWire.kind === "config"
                  ? "#c2410c"
                  : liveWire.kind === "error"
                    ? "#dc2626"
                    : "#3b82f6"
              }
              strokeWidth="2"
              strokeDasharray="5 4"
            />
          )}
        </svg>

        {topLevelNodes.map((node) => {
          const meta = metaOf(node);
          if (!meta) return null;
          const color = CATEGORY_COLORS[meta.category];
          const status = node.runStatus;
          const isAux = meta.kind === "aux";
          const isContainer = meta.kind === "container";
          const size = sizeFor(meta);
          const child = isContainer
            ? nodes.find((item) => item.parent === node.id)
            : null;
          const childMeta = child ? metaOf(child) : null;
          const childColor = childMeta ? CATEGORY_COLORS[childMeta.category] : null;
          const childStatus = child?.runStatus;
          const dataAttrs = isContainer ? { "data-container-id": node.id } : {};
          return (
            <div
              key={node.id}
              {...dataAttrs}
              data-node-id={node.id}
              className={`wf-node${isContainer ? " wf-container" : ""}${
                selected === node.id ? " selected" : ""
              }${status ? ` run-${status}` : ""}${isAux ? " wf-aux" : ""}`}
              style={{ left: node.x, top: node.y, width: size.w, height: size.h }}
              onMouseDown={(event) => beginNodeDrag(event, node)}
              onDoubleClick={() => onOpenParams(node.id)}
              title={`${meta.name} - ${meta.desc}`}
            >
              {!isContainer && (
                <>
                  <div
                    className="wf-node-icon"
                    style={{
                      background: color.bg,
                      color: color.fg,
                      borderColor: color.dot,
                    }}
                    dangerouslySetInnerHTML={{
                      __html: XFLOWS_ICONS[meta.icon] || "",
                    }}
                  />
                  <div className="wf-node-label">
                    <div className="wf-node-name">{meta.name}</div>
                    <div className="wf-node-meta">
                      {status === "running" && (
                        <span className="wf-run-mini running">
                          <span className="wf-spinner sm" />
                        </span>
                      )}
                      {status === "success" && (
                        <span className="wf-run-mini ok">
                          {" "}
                          {node.duration != null ? `${Math.round(node.duration)}ms` : "ok"}
                        </span>
                      )}
                      {status === "error" && <span className="wf-run-mini err">failed</span>}
                      {status === "skipped" && (
                        <span className="wf-run-mini skip">skipped</span>
                      )}
                      {!status && (
                        <span className="wf-node-cat" style={{ color: color.fg }}>
                          {meta.category}
                        </span>
                      )}
                    </div>
                  </div>
                </>
              )}
              {isContainer && (
                <div className="wf-container-inner">
                  <div className="wf-container-head">
                    <div
                      className="wf-node-icon"
                      style={{
                        background: color.bg,
                        color: color.fg,
                        borderColor: color.dot,
                      }}
                      dangerouslySetInnerHTML={{
                        __html: XFLOWS_ICONS[meta.icon] || "",
                      }}
                    />
                    <div className="wf-container-title">{meta.name}</div>
                  </div>
                  {child && childMeta ? (
                    <div
                      className={`wf-inner-chip${selected === child.id ? " selected" : ""}${
                        childStatus ? ` run-${childStatus}` : ""
                      }`}
                      onMouseDown={(event) => {
                        event.stopPropagation();
                        onSelect(child.id);
                      }}
                      onDoubleClick={(event) => {
                        event.stopPropagation();
                        onOpenParams(child.id);
                      }}
                    >
                      <div
                        className="wf-inner-icon"
                        style={{
                          background: childColor.bg,
                          color: childColor.fg,
                          borderColor: childColor.dot,
                        }}
                        dangerouslySetInnerHTML={{
                          __html: XFLOWS_ICONS[childMeta.icon] || "",
                        }}
                      />
                      <div className="wf-inner-name">{childMeta.name}</div>
                      <button
                        className="wf-inner-x"
                        onClick={(event) => {
                          event.stopPropagation();
                          onDelete(child.id);
                        }}
                        title="Remove provider"
                      >
                        x
                      </button>
                    </div>
                  ) : (
                    <div className="wf-inner-drop">Drop a provider here</div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* Ports live above the nodes in canvas coordinates rather than inside
            the node box. `portsForNode` places the bubble and `sourcePortPos` /
            `targetPortPos` place the wire ends, so the two cannot drift apart
            the way a CSS offset and a JS constant did. Which bubbles a node
            gets is decided by `kind`, never by category: every executing node
            offers both outputs — data and error — because any executor can
            throw, triggers and the terminal Output included. Aux nodes are the
            one exception: they attach to a container's config slot, so they
            carry a config bubble instead. */}
        <div className="wf-ports-layer">
          {topLevelNodes.map((node) => {
            const meta = metaOf(node);
            if (!meta) return null;
            return portsForNode(node, meta).map((port) => (
              <div
                key={port.key}
                className={`wf-port ${port.className}`}
                data-port={port.port}
                data-node-id={node.id}
                data-slot={port.slot}
                style={{ left: port.x, top: port.y }}
                title={port.title}
                onMouseDown={(event) => startWire(event, node, port)}
              >
                {port.label && <span className="wf-slot-label">{port.label}</span>}
              </div>
            ));
          })}
        </div>
      </div>

      {connectMenu && (
        <ConnectMenu
          pending={connectMenu.wire}
          nodes={nodes}
          edges={edges}
          position={connectMenu.at}
          bounds={connectMenu.bounds}
          onChoose={chooseConnection}
          onClose={closeConnectMenu}
        />
      )}

      <div className="wf-canvas-controls">
        <button onClick={() => setView({ x: 0, y: 0, k: 1 })}>Reset</button>
        <button
          onClick={() =>
            setView((current) => ({ ...current, k: Math.min(2, current.k * 1.1) }))
          }
        >
          +
        </button>
        <button
          onClick={() =>
            setView((current) => ({ ...current, k: Math.max(0.4, current.k / 1.1) }))
          }
        >
          -
        </button>
        <span className="wf-zoom">{Math.round(view.k * 100)}%</span>
      </div>

      {(() => {
        const editingEdge = edges.find((edge) => edge.id === selected);
        if (!editingEdge || (editingEdge.kind !== "data" && editingEdge.kind !== "error")) {
          return null;
        }
        return (
          <div className="wf-edge-editor" onMouseDown={(event) => event.stopPropagation()}>
            <div className="wf-edge-editor-title">
              Edge · {editingEdge.kind || "data"}
            </div>
            <label className="wf-edge-editor-field">
              <span>Kind</span>
              <select
                value={editingEdge.kind || "data"}
                onChange={(event) => onUpdateEdge?.(editingEdge.id, { kind: event.target.value })}
              >
                <option value="data">data</option>
                <option value="error">error</option>
              </select>
            </label>
            <label className="wf-edge-editor-field">
              <span>When</span>
              <input
                value={editingEdge.when || ""}
                placeholder="e.g. value == 'approved'"
                onChange={(event) => onUpdateEdge?.(editingEdge.id, { when: event.target.value })}
              />
            </label>
            <div className="wf-edge-editor-actions">
              <button
                onClick={() => {
                  onDeleteEdge?.(editingEdge.id);
                }}
              >
                Delete
              </button>
              <button
                onClick={() => {
                  onSelect(null);
                }}
              >
                Close
              </button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

export default Canvas;
