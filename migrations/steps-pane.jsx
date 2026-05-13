// Right pane: Steps · Test · Validation
const { useState: useS1, useMemo: useM1, useRef: useR1 } = React;

function StepsPane({
  nodes, edges, selected, onSelect, onOpenParams, onDelete,
  onRun, runState, apiKeys, setApiKeys,
}) {
  const validation = useM1(() => window.XFlowsEngine.validate(nodes, edges), [nodes, edges]);
  const [tab, setTab] = useS1('properties');
  const selectedNode = selected && !String(selected).startsWith('e_') ? nodes.find(n => n.id === selected) : null;
  React.useEffect(() => { if (selectedNode) setTab('properties'); }, [selected]);

  const orderedNodes = useM1(() => {
    if (!validation.order || validation.order.length === 0) return nodes;
    return validation.order.map(id => nodes.find(n => n.id === id)).filter(Boolean);
  }, [validation.order, nodes]);

  return (
    <aside className="right-pane">
      <div className="right-tabs">
        <button className={tab === 'properties' ? 'active' : ''} onClick={() => setTab('properties')}>
          Properties
        </button>
        <button className={tab === 'steps' ? 'active' : ''} onClick={() => setTab('steps')}>
          Steps <span className="badge">{nodes.length}</span>
        </button>
        <button className={tab === 'test' ? 'active' : ''} onClick={() => setTab('test')}>
          Test
          {runState.events.some(e => e.type === 'error') && <span className="badge err">!</span>}
        </button>
        <button className={tab === 'validation' ? 'active' : ''} onClick={() => setTab('validation')}>
          Validation
          {validation.errors.length > 0 && <span className="badge err">{validation.errors.length}</span>}
        </button>
      </div>

      {tab === 'properties' && (
        <div className="pane-body">
          {selectedNode ? (
            <window.PropertiesPanel
              node={selectedNode}
              onSave={(p) => {
                // mutate via onOpenParams pattern not available; emit edit via global
                window.__xflows_updateParams?.(selectedNode.id, p);
              }}
            />
          ) : (
            <div className="empty">
              <div className="empty-title">No node selected</div>
              <div className="empty-sub">Click a node on the canvas to configure it.</div>
            </div>
          )}
        </div>
      )}

      {tab === 'steps' && (
        <div className="pane-body">
          {orderedNodes.length === 0 && (
            <div className="empty">
              <div className="empty-title">No nodes yet</div>
              <div className="empty-sub">Drag a node from the left sidebar onto the canvas.</div>
            </div>
          )}
          <ol className="step-list">
            {orderedNodes.map((n, i) => {
              const meta = window.XFLOWS_CATALOG.find(c => c.id === n.componentId);
              if (!meta) return null;
              const color = window.CATEGORY_COLORS[meta.category];
              const isSel = selected === n.id;
              return (
                <li key={n.id} className={'step-row' + (isSel ? ' selected' : '')} onClick={() => onSelect(n.id)}>
                  <div className="step-num">{i + 1}</div>
                  <div className="step-main">
                    <div className="step-head">
                      <span className="cat-dot" style={{ background: color.dot }} />
                      <span className="step-name">{meta.name}</span>
                      <span className="step-cat" style={{ color: color.fg, background: color.bg }}>{meta.category}</span>
                    </div>
                    <div className="step-params">
                      {(meta.params || []).slice(0, 3).map(p => {
                        const v = (n.params && p.name in n.params) ? n.params[p.name] : p.default;
                        if (v === '' || v === null || v === undefined) return null;
                        const sv = String(v).slice(0, 24);
                        return (
                          <span className="param-pill" key={p.name}>
                            <span className="pk">{p.name}</span>
                            <span className="pv">{sv}</span>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                  <div className="step-actions">
                    <button title="Configure" onClick={(e) => { e.stopPropagation(); onOpenParams(n.id); }}>⚙</button>
                    <button title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(n.id); }}>✕</button>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {tab === 'test' && (
        <TestPanel
          nodes={nodes} edges={edges}
          onRun={onRun} runState={runState}
          apiKeys={apiKeys} setApiKeys={setApiKeys}
          canRun={validation.errors.length === 0}
          validationErrors={validation.errors}
        />
      )}

      {tab === 'validation' && (
        <div className="pane-body">
          {validation.errors.length === 0 ? (
            <div className="valid-ok">
              <div className="ok-mark">✓</div>
              <div className="ok-title">Workflow is valid</div>
              <div className="ok-sub">{nodes.length} nodes · ready to run</div>
            </div>
          ) : (
            <ul className="valid-list">
              {validation.errors.map((e, i) => (
                <li key={i} className="valid-row err">
                  <span className="bullet">!</span>
                  <span>{e}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}

function TestPanel({ nodes, edges, onRun, runState, apiKeys, setApiKeys, canRun, validationErrors }) {
  const [input, setInput] = useS1('What is the capital of France?');
  const [showKeys, setShowKeys] = useS1(false);
  const logRef = useR1(null);

  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [runState.events.length]);

  const usesOpenAI = nodes.some(n => n.componentId === 'OpenAIChat');

  return (
    <div className="pane-body test-body">
      <div className="test-section">
        <div className="test-label">Test input</div>
        <textarea
          className="test-input"
          rows={3}
          placeholder="Type a test message…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <div className="test-actions">
          <button className="keys-btn" onClick={() => setShowKeys(s => !s)}>
            🔑 API keys {usesOpenAI && !apiKeys.openai ? <span className="key-warn">required</span> : null}
          </button>
          <button
            className={'run-btn' + (canRun && !runState.running ? '' : ' disabled')}
            onClick={() => canRun && !runState.running && onRun(input)}
            disabled={!canRun || runState.running}
          >
            {runState.running ? <><span className="spinner" /> Running…</> : <>▶ Run workflow</>}
          </button>
        </div>
        {showKeys && (
          <div className="keys-panel">
            <div className="field">
              <label><span className="field-name">OpenAI API key</span></label>
              <input
                type="password"
                placeholder="sk-…"
                value={apiKeys.openai || ''}
                onChange={(e) => setApiKeys({ ...apiKeys, openai: e.target.value })}
              />
              <div className="field-help">Stored only in this browser session. Used by OpenAI Chat nodes.</div>
            </div>
          </div>
        )}
        {!canRun && validationErrors.length > 0 && (
          <div className="test-warn">Fix validation errors before running.</div>
        )}
      </div>

      <div className="test-section">
        <div className="test-label">Execution trace</div>
        <div className="trace-log" ref={logRef}>
          {runState.events.length === 0 && (
            <div className="empty-mini">No runs yet. Press Run to execute.</div>
          )}
          {runState.events.map((e, i) => {
            const node = nodes.find(n => n.id === e.nodeId);
            const meta = node ? window.XFLOWS_CATALOG.find(c => c.id === node.componentId) : null;
            const name = meta?.name || '—';
            if (e.type === 'start') return (
              <div key={i} className="trace-row">
                <span className="trace-icon running"><span className="spinner sm" /></span>
                <span className="trace-name">{name}</span>
                <span className="trace-msg">started</span>
              </div>
            );
            if (e.type === 'success') return (
              <div key={i} className="trace-row">
                <span className="trace-icon ok">✓</span>
                <span className="trace-name">{name}</span>
                <span className="trace-msg">{e.duration ? Math.round(e.duration) + 'ms' : ''}</span>
                {e.output != null && <div className="trace-output">{String(e.output).slice(0, 200)}{String(e.output).length > 200 ? '…' : ''}</div>}
              </div>
            );
            if (e.type === 'error') return (
              <div key={i} className="trace-row">
                <span className="trace-icon err">✕</span>
                <span className="trace-name">{name}</span>
                <span className="trace-msg err">{e.error}</span>
              </div>
            );
            return null;
          })}
        </div>
      </div>

      {runState.finalOutput != null && (
        <div className="test-section">
          <div className="test-label">Final output</div>
          <pre className="final-output">{runState.finalOutput}</pre>
        </div>
      )}
    </div>
  );
}

window.StepsPane = StepsPane;
