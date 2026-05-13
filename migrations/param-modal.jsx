// Parameter configuration modal
const { useState: useSp, useEffect: useEp } = React;

function ParamModal({ node, onClose, onSave }) {
  const meta = window.XFLOWS_CATALOG.find(c => c.id === node.componentId);
  const [vals, setVals] = useSp(() => {
    const out = {};
    for (const p of meta.params) {
      out[p.name] = (node.params && p.name in node.params) ? node.params[p.name] : p.default;
    }
    return out;
  });

  useEp(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const set = (k, v) => setVals(prev => ({ ...prev, [k]: v }));
  const color = window.CATEGORY_COLORS[meta.category];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">
            <span className="cat-dot" style={{ background: color.dot }} />
            <span>{meta.name}</span>
            <span className="modal-mod">{meta.category}</span>
          </div>
          <button className="x-btn" onClick={onClose}>✕</button>
        </div>
        <div className="modal-desc">{meta.desc}</div>
        <div className="modal-body">
          {meta.params.length === 0 && (
            <div className="empty-mini">No parameters to configure.</div>
          )}
          {meta.params.map(p => (
            <div className="field" key={p.name}>
              <label>
                <span className="field-name">{p.name}</span>
                <span className="field-default">default: {String(p.default).slice(0, 30)}</span>
              </label>
              {p.type === 'select' && (
                <select value={vals[p.name] ?? p.default} onChange={(e) => set(p.name, e.target.value)}>
                  {p.options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              )}
              {p.type === 'number' && (
                <input
                  type="number"
                  step={p.step || 1}
                  value={vals[p.name] ?? ''}
                  onChange={(e) => set(p.name, e.target.value === '' ? '' : Number(e.target.value))}
                />
              )}
              {p.type === 'text' && (
                <input
                  type="text"
                  value={vals[p.name] ?? ''}
                  onChange={(e) => set(p.name, e.target.value)}
                />
              )}
              {p.type === 'textarea' && (
                <textarea
                  rows={5}
                  value={vals[p.name] ?? ''}
                  onChange={(e) => set(p.name, e.target.value)}
                />
              )}
              {p.type === 'bool' && (
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={!!vals[p.name]}
                    onChange={(e) => set(p.name, e.target.checked)}
                  />
                  <span>{vals[p.name] ? 'True' : 'False'}</span>
                </label>
              )}
              {p.help && <div className="field-help">{p.help}</div>}
            </div>
          ))}
        </div>
        <div className="modal-foot">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={() => { onSave(vals); onClose(); }}>Save parameters</button>
        </div>
      </div>
    </div>
  );
}

window.ParamModal = ParamModal;
