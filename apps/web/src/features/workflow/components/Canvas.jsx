import { useEffect, useMemo, useRef, useState } from "react";
import {
  CATEGORY_COLORS,
  XFLOWS_ICONS,
  getComponentMeta,
} from "../catalog/catalog-meta";

const NODE_W = 132;
const NODE_H = 46;
const CONT_W = 200;
const CONT_H = 110;
const PORT_SIZE = 10;
const CONFIG_PORT_SIZE = 9;
const PORT_OVERHANG = 6;

function sizeFor(meta) {
  if (meta?.kind === "container") return { w: CONT_W, h: CONT_H };
  return { w: NODE_W, h: NODE_H };
}

function Canvas({
  nodes,
  edges,
  selected,
  onSelect,
  onNodeMove,
  onNodeAdd,
  onConnect,
  onDelete,
  onOpenParams,
}) {
  const wrapRef = useRef(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [drag, setDrag] = useState(null);
  const [pendingWire, setPendingWire] = useState(null);

  const nodeById = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.id, node])),
    [nodes]
  );
  const metaOf = (node) => getComponentMeta(node.componentId);

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

  const onDrop = (event) => {
    event.preventDefault();
    const componentId = event.dataTransfer.getData("component-id");
    if (!componentId) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const x = (event.clientX - rect.left - view.x) / view.k - NODE_W / 2;
    const y = (event.clientY - rect.top - view.y) / view.k - NODE_H / 2;
    const el = document.elementFromPoint(event.clientX, event.clientY);
    const containerEl = el?.closest?.("[data-container-id]");
    const targetId = containerEl?.dataset?.containerId || null;
    onNodeAdd(componentId, { x, y }, targetId);
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

  const onMouseUp = (event) => {
    setDrag(null);
    if (pendingWire) {
      const el = document.elementFromPoint(event.clientX, event.clientY);
      if (pendingWire.kind === "data") {
        const target = el?.closest?.("[data-port='in']");
        if (target && target.dataset.nodeId !== pendingWire.from) {
          onConnect(pendingWire.from, target.dataset.nodeId, "data");
        }
      } else if (pendingWire.kind === "config") {
        const target = el?.closest?.("[data-port='config-in']");
        if (target && target.dataset.nodeId !== pendingWire.from) {
          onConnect(
            pendingWire.from,
            target.dataset.nodeId,
            "config",
            target.dataset.slot
          );
        }
      }
      setPendingWire(null);
    }
  };

  useEffect(() => {
    const stop = () => {
      setDrag(null);
      setPendingWire(null);
    };
    window.addEventListener("mouseup", stop);
    return () => window.removeEventListener("mouseup", stop);
  }, []);

  const dataPortPos = (node, side) => {
    const size = sizeFor(metaOf(node));
    return { x: node.x + (side === "in" ? 0 : size.w), y: node.y + size.h / 2 };
  };

  const configOutPortPos = (node) => {
    const size = sizeFor(metaOf(node));
    return {
      x: node.x + size.w / 2,
      y: node.y - PORT_OVERHANG + PORT_SIZE / 2,
    };
  };

  const configPortPos = (node, slotIdx, totalSlots) => {
    const size = sizeFor(metaOf(node));
    const step = size.w / (totalSlots + 1);
    return {
      x: node.x + step * (slotIdx + 1),
      y: node.y + size.h + PORT_OVERHANG - CONFIG_PORT_SIZE / 2,
    };
  };

  const edgePath = (a, b, vertical = false) => {
    if (vertical) {
      const dy = Math.max(30, Math.abs(b.y - a.y) * 0.5);
      const direction = b.y >= a.y ? 1 : -1;
      return `M ${a.x} ${a.y} C ${a.x} ${a.y + dy * direction}, ${b.x} ${b.y - dy * direction}, ${b.x} ${b.y}`;
    }
    const dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
    return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  };

  const startDataWire = (event, nodeId) => {
    event.stopPropagation();
    const node = nodeById[nodeId];
    const p = dataPortPos(node, "out");
    setPendingWire({
      from: nodeId,
      kind: "data",
      sx: p.x,
      sy: p.y,
      tx: p.x,
      ty: p.y,
    });
  };

  const startConfigWire = (event, nodeId) => {
    event.stopPropagation();
    const node = nodeById[nodeId];
    const p = configOutPortPos(node);
    setPendingWire({
      from: nodeId,
      kind: "config",
      sx: p.x,
      sy: p.y,
      tx: p.x,
      ty: p.y,
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
          </defs>
          {edges.map((edge) => {
            const sourceNode = nodeById[edge.source];
            const targetNode = nodeById[edge.target];
            if (!sourceNode || !targetNode) return null;
            const isConfig = edge.kind === "config";
            let sourcePort;
            let targetPort;
            if (isConfig) {
              const targetMeta = metaOf(targetNode);
              const slots = targetMeta?.configs || [];
              const idx = Math.max(
                0,
                slots.findIndex((slot) => slot.name === edge.slot)
              );
              sourcePort = configOutPortPos(sourceNode);
              targetPort = configPortPos(targetNode, idx, slots.length || 1);
            } else {
              sourcePort = dataPortPos(sourceNode, "out");
              targetPort = dataPortPos(targetNode, "in");
            }
            return (
              <g key={edge.id}>
                <path
                  d={edgePath(sourcePort, targetPort, isConfig)}
                  className={`wf-edge${isConfig ? " config" : ""}${
                    selected === edge.id ? " selected" : ""
                  }${edge.activeEdge ? " active" : ""}`}
                  fill="none"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(edge.id);
                  }}
                  markerEnd={isConfig ? "url(#wf-arrow-config)" : "url(#wf-arrow)"}
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
          {pendingWire && (
            <path
              d={edgePath(
                { x: pendingWire.sx, y: pendingWire.sy },
                { x: pendingWire.tx, y: pendingWire.ty },
                pendingWire.kind === "config"
              )}
              fill="none"
              stroke={pendingWire.kind === "config" ? "#c2410c" : "#3b82f6"}
              strokeWidth="2"
              strokeDasharray="5 4"
            />
          )}
        </svg>

        {nodes
          .filter((node) => !node.parent)
          .map((node) => {
            const meta = metaOf(node);
            if (!meta) return null;
            const color = CATEGORY_COLORS[meta.category];
            const status = node.runStatus;
            const isAux = meta.category === "Observability" || meta.id === "VectorStore";
            const isContainer = meta.kind === "container";
            const configs = meta.configs || [];
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
                className={`wf-node${isContainer ? " wf-container" : ""}${
                  selected === node.id ? " selected" : ""
                }${status ? ` run-${status}` : ""}${isAux ? " wf-aux" : ""}`}
                style={{ left: node.x, top: node.y, width: size.w, height: size.h }}
                onMouseDown={(event) => {
                  event.stopPropagation();
                  onSelect(node.id);
                  const rect = wrapRef.current.getBoundingClientRect();
                  const ox = (event.clientX - rect.left - view.x) / view.k - node.x;
                  const oy = (event.clientY - rect.top - view.y) / view.k - node.y;
                  setDrag({ type: "node", id: node.id, ox, oy });
                }}
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

                {meta.kind !== "input" && meta.category !== "Observability" && (
                  <div className="wf-port wf-port-in" data-port="in" data-node-id={node.id} />
                )}
                {meta.kind !== "output" && meta.category !== "Observability" && (
                  <div
                    className="wf-port wf-port-out"
                    data-port="out"
                    data-node-id={node.id}
                    onMouseDown={(event) => startDataWire(event, node.id)}
                  />
                )}
                {(meta.category === "Observability" ||
                  meta.category === "Memory" ||
                  meta.category === "Tool") && (
                  <div
                    className="wf-port wf-port-config-out"
                    data-port="config-out"
                    data-node-id={node.id}
                    onMouseDown={(event) => startConfigWire(event, node.id)}
                  />
                )}
                {configs.map((slot, idx) => {
                  const step = 100 / (configs.length + 1);
                  return (
                    <div
                      key={slot.name}
                      className="wf-port wf-port-config-in"
                      data-port="config-in"
                      data-node-id={node.id}
                      data-slot={slot.name}
                      style={{ left: `${step * (idx + 1)}%` }}
                      title={`${slot.label || slot.name} (accepts ${slot.accepts.join(", ")})`}
                    >
                      <span className="wf-slot-label">{slot.label || slot.name}</span>
                    </div>
                  );
                })}
              </div>
            );
          })}
      </div>

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
    </div>
  );
}

export default Canvas;
