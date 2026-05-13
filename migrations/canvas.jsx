// Canvas — compact icon nodes, data ports (left/right) + config ports (bottom)
const { useState, useRef, useEffect, useMemo } = React;

const NODE_W = 132;
const NODE_H = 46;
const CONT_W = 200;
const CONT_H = 110;

function sizeFor(meta) {
  if (meta?.kind === 'container') return { w: CONT_W, h: CONT_H };
  return { w: NODE_W, h: NODE_H };
}

function Canvas({
  nodes, edges, selected, onSelect,
  onNodeMove, onNodeAdd, onConnect, onDelete,
  onOpenParams,
}) {
  const wrapRef = useRef(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [drag, setDrag] = useState(null);
  const [pendingWire, setPendingWire] = useState(null);

  const onWheel = (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const rect = wrapRef.current.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      const k2 = Math.max(0.4, Math.min(2, view.k * factor));
      const x2 = mx - (mx - view.x) * (k2 / view.k);
      const y2 = my - (my - view.y) * (k2 / view.k);
      setView({ x: x2, y: y2, k: k2 });
    } else {
      setView((v) => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    const componentId = e.dataTransfer.getData('component-id');
    if (!componentId) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left - view.x) / view.k - NODE_W / 2;
    const y = (e.clientY - rect.top - view.y) / view.k - NODE_H / 2;
    // detect container under cursor
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const containerEl = el?.closest?.('[data-container-id]');
    const targetId = containerEl?.dataset?.containerId || null;
    onNodeAdd(componentId, { x, y }, targetId);
  };

  const onMouseDown = (e) => {
    if (e.target === wrapRef.current || e.target.dataset.bg === '1') {
      setDrag({ type: 'pan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y });
      onSelect(null);
    }
  };

  const onMouseMove = (e) => {
    if (!drag && !pendingWire) return;
    const rect = wrapRef.current.getBoundingClientRect();
    if (drag?.type === 'pan') {
      setView((v) => ({ ...v, x: drag.vx + (e.clientX - drag.sx), y: drag.vy + (e.clientY - drag.sy) }));
    } else if (drag?.type === 'node') {
      const x = (e.clientX - rect.left - view.x) / view.k - drag.ox;
      const y = (e.clientY - rect.top - view.y) / view.k - drag.oy;
      onNodeMove(drag.id, { x, y });
    } else if (pendingWire) {
      const x = (e.clientX - rect.left - view.x) / view.k;
      const y = (e.clientY - rect.top - view.y) / view.k;
      setPendingWire({ ...pendingWire, tx: x, ty: y });
    }
  };

  const onMouseUp = (e) => {
    setDrag(null);
    if (pendingWire) {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      if (pendingWire.kind === 'data') {
        const t = el?.closest?.('[data-port="in"]');
        if (t && t.dataset.nodeId !== pendingWire.from) onConnect(pendingWire.from, t.dataset.nodeId, 'data');
      } else if (pendingWire.kind === 'config') {
        const t = el?.closest?.('[data-port="config-in"]');
        if (t && t.dataset.nodeId !== pendingWire.from) {
          onConnect(pendingWire.from, t.dataset.nodeId, 'config', t.dataset.slot);
        }
      }
      setPendingWire(null);
    }
  };

  useEffect(() => {
    const stop = () => { setDrag(null); setPendingWire(null); };
    window.addEventListener('mouseup', stop);
    return () => window.removeEventListener('mouseup', stop);
  }, []);

  const nodeById = useMemo(() => Object.fromEntries(nodes.map(n => [n.id, n])), [nodes]);
  const metaOf = (n) => window.XFLOWS_CATALOG.find(c => c.id === n.componentId);

  const dataPortPos = (n, side) => {
    const s = sizeFor(metaOf(n));
    return { x: n.x + (side === 'in' ? 0 : s.w), y: n.y + s.h / 2 };
  };

  const configPortPos = (n, slotIdx, totalSlots) => {
    const s = sizeFor(metaOf(n));
    const step = s.w / (totalSlots + 1);
    return { x: n.x + step * (slotIdx + 1), y: n.y + s.h };
  };

  const edgePath = (a, b, vertical = false) => {
    if (vertical) {
      const dy = Math.max(30, Math.abs(b.y - a.y) * 0.5);
      return `M ${a.x} ${a.y} C ${a.x} ${a.y + dy}, ${b.x} ${b.y - dy}, ${b.x} ${b.y}`;
    }
    const dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
    return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  };

  const startDataWire = (e, nodeId) => {
    e.stopPropagation();
    const n = nodeById[nodeId];
    const p = dataPortPos(n, 'out');
    setPendingWire({ from: nodeId, kind: 'data', sx: p.x, sy: p.y, tx: p.x, ty: p.y });
  };

  const startConfigWire = (e, nodeId) => {
    e.stopPropagation();
    const n = nodeById[nodeId];
    const s = sizeFor(metaOf(n));
    const p = { x: n.x + s.w / 2, y: n.y };
    setPendingWire({ from: nodeId, kind: 'config', sx: p.x, sy: p.y, tx: p.x, ty: p.y });
  };

  return (
    <div
      ref={wrapRef}
      data-bg="1"
      className="canvas-wrap"
      onWheel={onWheel}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
    >
      <div className="canvas-grid" style={{
        backgroundPosition: `${view.x}px ${view.y}px`,
        backgroundSize: `${24 * view.k}px ${24 * view.k}px`,
      }} data-bg="1" />

      <div className="canvas-inner" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
        <svg className="edges" width="6000" height="6000">
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
              <path d="M 0 0 L 8 5 L 0 10 z" fill="#111" />
            </marker>
            <marker id="arrow-config" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
              <path d="M 0 0 L 8 5 L 0 10 z" fill="#c2410c" />
            </marker>
          </defs>
          {edges.map((e) => {
            const a = nodeById[e.source]; const b = nodeById[e.target];
            if (!a || !b) return null;
            const isConfig = e.kind === 'config';
            let pa, pb;
            if (isConfig) {
              // aux top → target's bottom config slot
              const tMeta = metaOf(b);
              const slots = tMeta?.configs || [];
              const idx = Math.max(0, slots.findIndex(s => s.name === e.slot));
              const sa = sizeFor(metaOf(a));
              pa = { x: a.x + sa.w / 2, y: a.y };
              pb = configPortPos(b, idx, slots.length || 1);
            } else {
              pa = dataPortPos(a, 'out');
              pb = dataPortPos(b, 'in');
            }
            const active = e.activeEdge;
            return (
              <g key={e.id}>
                <path
                  d={edgePath(pa, pb, isConfig)}
                  className={'edge' + (isConfig ? ' config' : '') + (selected === e.id ? ' selected' : '') + (active ? ' active' : '')}
                  fill="none"
                  onClick={(ev) => { ev.stopPropagation(); onSelect(e.id); }}
                  markerEnd={isConfig ? 'url(#arrow-config)' : 'url(#arrow)'}
                />
                {active && <path d={edgePath(pa, pb, isConfig)} className="edge-flow" fill="none" />}
              </g>
            );
          })}
          {pendingWire && (
            <path
              d={edgePath({ x: pendingWire.sx, y: pendingWire.sy }, { x: pendingWire.tx, y: pendingWire.ty }, pendingWire.kind === 'config')}
              fill="none"
              stroke={pendingWire.kind === 'config' ? '#c2410c' : '#3b82f6'}
              strokeWidth="2" strokeDasharray="5 4"
            />
          )}
        </svg>

        {nodes.filter(n => !n.parent).map((n) => {
          const m = metaOf(n);
          if (!m) return null;
          const color = window.CATEGORY_COLORS[m.category];
          const status = n.runStatus;
          const isAux = m.category === 'Observability' || m.id === 'VectorStore';
          const isContainer = m.kind === 'container';
          const configs = m.configs || [];
          const sz = sizeFor(m);
          const child = isContainer ? nodes.find(x => x.parent === n.id) : null;
          const childMeta = child && metaOf(child);
          const childColor = childMeta && window.CATEGORY_COLORS[childMeta.category];
          const childStatus = child?.runStatus;
          const dataAttrs = isContainer ? { 'data-container-id': n.id } : {};
          return (
            <div
              key={n.id}
              {...dataAttrs}
              className={'node ' + (isContainer ? 'container ' : '') + (selected === n.id ? 'selected ' : '') + (status ? 'run-' + status + ' ' : '') + (isAux ? 'aux ' : '')}
              style={{ left: n.x, top: n.y, width: sz.w, height: sz.h }}
              onMouseDown={(e) => {
                e.stopPropagation();
                onSelect(n.id);
                const rect = wrapRef.current.getBoundingClientRect();
                const ox = (e.clientX - rect.left - view.x) / view.k - n.x;
                const oy = (e.clientY - rect.top - view.y) / view.k - n.y;
                setDrag({ type: 'node', id: n.id, ox, oy });
              }}
              onDoubleClick={() => onOpenParams(n.id)}
              title={`${m.name} — ${m.desc}`}
            >
              {!isContainer && (
                <>
                  <div className="node-icon" style={{ background: color.bg, color: color.fg, borderColor: color.dot }}
                       dangerouslySetInnerHTML={{ __html: window.XFLOWS_ICONS[m.icon] || '' }} />
                  <div className="node-label">
                    <div className="node-name">{m.name}</div>
                    <div className="node-meta">
                      {status === 'running' && <span className="run-mini running"><span className="spinner sm" /></span>}
                      {status === 'success' && <span className="run-mini ok">✓ {n.duration != null ? Math.round(n.duration) + 'ms' : ''}</span>}
                      {status === 'error' && <span className="run-mini err">✕ failed</span>}
                      {!status && <span className="node-cat" style={{ color: color.fg }}>{m.category}</span>}
                    </div>
                  </div>
                </>
              )}
              {isContainer && (
                <div className="container-inner">
                  <div className="container-head">
                    <div className="node-icon" style={{ background: color.bg, color: color.fg, borderColor: color.dot }}
                         dangerouslySetInnerHTML={{ __html: window.XFLOWS_ICONS[m.icon] || '' }} />
                    <div className="container-title">{m.name}</div>
                    {status === 'running' && <span className="run-mini running"><span className="spinner sm" /></span>}
                    {status === 'success' && <span className="run-mini ok">✓ {n.duration != null ? Math.round(n.duration) + 'ms' : ''}</span>}
                    {status === 'error' && <span className="run-mini err">✕ failed</span>}
                  </div>
                  {child && childMeta ? (
                    <div
                      className={'inner-chip ' + (selected === child.id ? 'selected ' : '') + (childStatus ? 'run-' + childStatus : '')}
                      onMouseDown={(e) => { e.stopPropagation(); onSelect(child.id); }}
                      onDoubleClick={(e) => { e.stopPropagation(); onOpenParams(child.id); }}
                      title={`${childMeta.name} — click to configure`}
                    >
                      <div className="inner-icon" style={{ background: childColor.bg, color: childColor.fg, borderColor: childColor.dot }}
                           dangerouslySetInnerHTML={{ __html: window.XFLOWS_ICONS[childMeta.icon] || '' }} />
                      <div className="inner-name">{childMeta.name}</div>
                      <button className="inner-x" onClick={(e) => { e.stopPropagation(); onSelect(child.id); setTimeout(onDelete, 0); }} title="Remove provider">✕</button>
                    </div>
                  ) : (
                    <div className="inner-drop">Drop a provider here</div>
                  )}
                </div>
              )}

              {/* Data input port (left) — hidden for input-kind & pure-aux observability */}
              {m.kind !== 'input' && m.category !== 'Observability' && (
                <div className="port port-in" data-port="in" data-node-id={n.id} title="data in" />
              )}
              {/* Data output port (right) — hidden for output-kind & pure-aux */}
              {m.kind !== 'output' && m.category !== 'Observability' && (
                <div
                  className="port port-out"
                  data-port="out"
                  data-node-id={n.id}
                  onMouseDown={(e) => startDataWire(e, n.id)}
                  title="data out"
                />
              )}

              {/* TOP port for aux nodes (Observability / Memory / Tool) — outputs to a config slot */}
              {(m.category === 'Observability' || m.category === 'Memory' || m.category === 'Tool') && (
                <div
                  className="port port-config-out"
                  data-port="config-out"
                  data-node-id={n.id}
                  onMouseDown={(e) => startConfigWire(e, n.id)}
                  title="connect to a config slot"
                />
              )}

              {/* BOTTOM config slot ports */}
              {configs.map((slot, idx) => {
                const step = 100 / (configs.length + 1);
                return (
                  <div
                    key={slot.name}
                    className="port port-config-in"
                    data-port="config-in"
                    data-node-id={n.id}
                    data-slot={slot.name}
                    style={{ left: `${step * (idx + 1)}%` }}
                    title={`${slot.label || slot.name} (accepts ${slot.accepts.join(', ')})`}
                  >
                    <span className="slot-label">{slot.label || slot.name}</span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="canvas-controls">
        <button onClick={() => setView({ x: 0, y: 0, k: 1 })}>Reset</button>
        <button onClick={() => setView((v) => ({ ...v, k: Math.min(2, v.k * 1.1) }))}>＋</button>
        <button onClick={() => setView((v) => ({ ...v, k: Math.max(0.4, v.k / 1.1) }))}>－</button>
        <span className="zoom">{Math.round(view.k * 100)}%</span>
      </div>
    </div>
  );
}

window.Canvas = Canvas;
