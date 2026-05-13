// XFlows — root app
const { useState: useSa, useEffect: useEa, useRef: useRa, useCallback: useCa, useMemo: useMa } = React;

function uid() { return 'n_' + Math.random().toString(36).slice(2, 9); }

const STARTER = () => {
  const a = uid(), b = uid(), llm = uid(), provider = uid(), d = uid(), t = uid();
  return {
    nodes: [
      { id: a, componentId: 'Input', x: 60, y: 180, params: {} },
      { id: b, componentId: 'PromptTemplate', x: 230, y: 180, params: { template: 'Answer concisely:\n\n{input}', system: 'You are a helpful assistant.' } },
      { id: llm, componentId: 'LLM', x: 420, y: 160, params: {} },
      { id: provider, componentId: 'OpenAIChat', parent: llm, params: { model: 'gpt-4o-mini', temperature: 0.7, max_tokens: 256 } },
      { id: d, componentId: 'Output', x: 680, y: 180, params: {} },
      { id: t, componentId: 'Tracer', x: 420, y: 320, params: { level: 'info', destination: 'both' } },
    ],
    edges: [
      { id: 'e1', source: a, target: b, kind: 'data' },
      { id: 'e2', source: b, target: llm, kind: 'data' },
      { id: 'e3', source: llm, target: d, kind: 'data' },
      { id: 'e4', source: t, target: llm, kind: 'config', slot: 'tracer' },
    ],
  };
};

function App() {
  const [{ nodes, edges }, setGraph] = useSa(STARTER);
  const [selected, setSelected] = useSa(null);
  const [editingNode, setEditingNode] = useSa(null);
  const [query, setQuery] = useSa('');
  const [history, setHistory] = useSa({ past: [], future: [] });
  const [toast, setToast] = useSa(null);

  // run state
  const [apiKeys, setApiKeys] = useSa(() => {
    try { return JSON.parse(sessionStorage.getItem('xflows_keys') || '{}'); } catch { return {}; }
  });
  useEa(() => { sessionStorage.setItem('xflows_keys', JSON.stringify(apiKeys)); }, [apiKeys]);

  const [runState, setRunState] = useSa({
    running: false,
    events: [],
    runStatus: {},      // nodeId -> 'running'|'success'|'error'
    durations: {},      // nodeId -> ms
    activeEdges: {},    // edgeId -> true
    finalOutput: null,
  });

  // ----- history helpers -----
  const commit = (next) => {
    setHistory(h => ({ past: [...h.past, { nodes, edges }].slice(-50), future: [] }));
    setGraph(next);
  };
  const undo = () => {
    setHistory(h => {
      if (!h.past.length) return h;
      const prev = h.past[h.past.length - 1];
      setGraph(prev);
      return { past: h.past.slice(0, -1), future: [{ nodes, edges }, ...h.future] };
    });
  };
  const redo = () => {
    setHistory(h => {
      if (!h.future.length) return h;
      const nxt = h.future[0];
      setGraph(nxt);
      return { past: [...h.past, { nodes, edges }], future: h.future.slice(1) };
    });
  };

  // ----- node ops -----
  const addNodeAt = (componentId, pos, dropTargetId) => {
    const meta = window.XFLOWS_CATALOG.find(c => c.id === componentId);
    if (!meta) return;
    // If dropped on a container that accepts this category, nest it
    if (dropTargetId) {
      const container = nodes.find(n => n.id === dropTargetId);
      const cMeta = container && window.XFLOWS_CATALOG.find(c => c.id === container.componentId);
      if (cMeta?.kind === 'container' && cMeta.accepts?.includes(meta.category)) {
        // replace existing child if any
        const filteredNodes = nodes.filter(n => n.parent !== container.id);
        const n = { id: uid(), componentId, parent: container.id, params: {} };
        commit({ nodes: [...filteredNodes, n], edges });
        setSelected(n.id);
        return;
      }
    }
    // Reject providers placed on empty canvas (they need a container)
    if (meta.kind === 'provider') {
      flash(`Drop ${meta.name} inside an ${meta.requiresContainer} container.`, 'err');
      return;
    }
    const n = { id: uid(), componentId, x: pos?.x ?? 200, y: pos?.y ?? 200, params: {} };
    commit({ nodes: [...nodes, n], edges });
    setSelected(n.id);
  };
  const addNodeQuick = (componentId) => addNodeAt(componentId, { x: 60 + nodes.length * 30, y: 80 + nodes.length * 30 });

  const moveNode = (id, pos) => {
    setGraph(g => ({ ...g, nodes: g.nodes.map(n => n.id === id ? { ...n, ...pos } : n) }));
  };

  const connect = (source, target, kind = 'data', slot) => {
    if (edges.some(e => e.source === source && e.target === target && (e.kind || 'data') === kind && e.slot === slot)) return;
    const edge = { id: 'e_' + uid(), source, target, kind };
    if (slot) edge.slot = slot;
    commit({ nodes, edges: [...edges, edge] });
  };

  const deleteSelected = useCa(() => {
    if (!selected) return;
    if (selected.startsWith('e_')) {
      commit({ nodes, edges: edges.filter(e => e.id !== selected) });
    } else {
      // remove node + any nested children + edges referencing any of them
      const toRemove = new Set([selected, ...nodes.filter(n => n.parent === selected).map(n => n.id)]);
      commit({
        nodes: nodes.filter(n => !toRemove.has(n.id)),
        edges: edges.filter(e => !toRemove.has(e.source) && !toRemove.has(e.target)),
      });
    }
    setSelected(null);
  }, [selected, nodes, edges]);

  const duplicateSelected = () => {
    if (!selected || selected.startsWith('e_')) return;
    const n = nodes.find(x => x.id === selected);
    if (!n) return;
    const copy = { ...n, id: uid(), x: n.x + 32, y: n.y + 32, params: { ...n.params } };
    commit({ nodes: [...nodes, copy], edges });
    setSelected(copy.id);
  };

  const updateNodeParams = (id, params) => {
    commit({ nodes: nodes.map(n => n.id === id ? { ...n, params } : n), edges });
  };
  React.useEffect(() => { window.__xflows_updateParams = updateNodeParams; });

  const clearAll = () => {
    if (nodes.length === 0) return;
    if (!window.confirm('Clear the entire canvas?')) return;
    commit({ nodes: [], edges: [] });
    setSelected(null);
  };

  // ----- save / load -----
  const saveJson = () => {
    const blob = new Blob([JSON.stringify({ nodes, edges }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'workflow.json'; a.click();
    URL.revokeObjectURL(url);
    flash('Saved workflow.json');
  };
  const loadJson = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        const data = JSON.parse(r.result);
        if (Array.isArray(data.nodes) && Array.isArray(data.edges)) {
          commit({ nodes: data.nodes, edges: data.edges });
          flash('Workflow loaded');
        }
      } catch { flash('Invalid file', 'err'); }
    };
    r.readAsText(file);
    e.target.value = '';
  };

  const flash = (msg, kind = 'ok') => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 1800);
  };

  // ----- keyboard shortcuts -----
  useEa(() => {
    const onKey = (e) => {
      const t = e.target;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return;
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); }
      else if ((e.metaKey || e.ctrlKey) && e.key === 'd') { e.preventDefault(); duplicateSelected(); }
      else if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
      else if ((e.metaKey || e.ctrlKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected, nodes, edges]);

  // ----- run -----
  const runWorkflow = async (userInput) => {
    setRunState({ running: true, events: [], runStatus: {}, durations: {}, activeEdges: {}, finalOutput: null });

    const onEvent = (ev) => {
      setRunState(prev => {
        const next = { ...prev, events: [...prev.events, ev] };
        if (ev.type === 'start') {
          next.runStatus = { ...prev.runStatus, [ev.nodeId]: 'running' };
        } else if (ev.type === 'success') {
          next.runStatus = { ...prev.runStatus, [ev.nodeId]: 'success' };
          next.durations = { ...prev.durations, [ev.nodeId]: ev.duration };
        } else if (ev.type === 'error') {
          next.runStatus = { ...prev.runStatus, [ev.nodeId]: 'error' };
          next.durations = { ...prev.durations, [ev.nodeId]: ev.duration };
        } else if (ev.type === 'edge') {
          const edge = edges.find(e => e.source === ev.source && e.target === ev.target);
          if (edge) {
            next.activeEdges = { ...prev.activeEdges, [edge.id]: true };
            // clear after a moment
            setTimeout(() => {
              setRunState(p => {
                const ae = { ...p.activeEdges }; delete ae[edge.id];
                return { ...p, activeEdges: ae };
              });
            }, 900);
          }
        }
        return next;
      });
    };

    try {
      const result = await window.XFlowsEngine.execute(nodes, edges, userInput, { apiKeys }, onEvent);
      setRunState(prev => ({ ...prev, running: false, finalOutput: result }));
      flash('Workflow completed');
    } catch (err) {
      setRunState(prev => ({ ...prev, running: false }));
      flash(err.message || 'Workflow failed', 'err');
    }
  };

  const validation = useMa(() => window.XFlowsEngine.validate(nodes, edges), [nodes, edges]);
  const editing = editingNode ? nodes.find(n => n.id === editingNode) : null;

  // decorate nodes & edges with run state
  const decoratedNodes = nodes.map(n => {
    const order = validation.order || [];
    const idx = order.indexOf(n.id);
    return {
      ...n,
      stepIndex: idx >= 0 ? idx + 1 : null,
      runStatus: runState.runStatus[n.id],
      duration: runState.durations[n.id],
    };
  });
  const decoratedEdges = edges.map(e => ({ ...e, activeEdge: !!runState.activeEdges[e.id] }));

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="4" cy="10" r="2.5" fill="#111"/><circle cx="16" cy="5" r="2.5" fill="#111"/><circle cx="16" cy="15" r="2.5" fill="#111"/><path d="M6 10 L14 5 M6 10 L14 15" stroke="#111" strokeWidth="1.5" fill="none"/></svg>
          </div>
          <div>
            <div className="brand-name">XFlows</div>
            <div className="brand-sub">visual agentic workflow builder</div>
          </div>
        </div>
        <div className="topbar-actions">
          <button className="tb-btn" onClick={undo} disabled={!history.past.length} title="Undo (⌘Z)">↺ Undo</button>
          <button className="tb-btn" onClick={redo} disabled={!history.future.length} title="Redo (⌘⇧Z)">↻ Redo</button>
          <span className="divider" />
          <label className="tb-btn">
            Load
            <input type="file" accept="application/json" onChange={loadJson} hidden />
          </label>
          <button className="tb-btn" onClick={saveJson}>Save</button>
          <button className="tb-btn" onClick={clearAll}>Clear</button>
        </div>
      </header>

      <div className="main">
        <div className="left-half">
          <window.ComponentPanel onAddNode={addNodeQuick} query={query} setQuery={setQuery} />
          <div className="canvas-host">
            <window.Canvas
              nodes={decoratedNodes}
              edges={decoratedEdges}
              selected={selected}
              onSelect={setSelected}
              onNodeMove={moveNode}
              onNodeAdd={addNodeAt}
              onConnect={connect}
              onDelete={deleteSelected}
              onOpenParams={(id) => setEditingNode(id)}
            />
            <div className="hint-overlay">
              <kbd>Drag</kbd> nodes in · <kbd>Drag</kbd> from a right port to connect · <kbd>Double-click</kbd> to configure
            </div>
          </div>
        </div>
        <window.StepsPane
          nodes={nodes}
          edges={edges}
          selected={selected}
          onSelect={setSelected}
          onOpenParams={(id) => setEditingNode(id)}
          onDelete={(id) => { setSelected(id); setTimeout(deleteSelected, 0); }}
          onRun={runWorkflow}
          runState={runState}
          apiKeys={apiKeys}
          setApiKeys={setApiKeys}
        />
      </div>

      {editing && (
        <window.ParamModal
          node={editing}
          onClose={() => setEditingNode(null)}
          onSave={(p) => updateNodeParams(editing.id, p)}
        />
      )}

      {toast && <div className={'toast ' + toast.kind}>{toast.msg}</div>}
      <window.XFlowsTweaks />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
