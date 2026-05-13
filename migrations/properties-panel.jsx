// Inline properties editor for selected node — lives in the right pane
function PropertiesPanel({ node, onSave }) {
  const meta = window.XFLOWS_CATALOG.find(c => c.id === node.componentId);
  if (!meta) return null;
  const color = window.CATEGORY_COLORS[meta.category];
  const [vals, setVals] = React.useState(() => {
    const out = {};
    for (const p of meta.params || []) {
      out[p.name] = (node.params && p.name in node.params) ? node.params[p.name] : p.default;
    }
    return out;
  });
  React.useEffect(() => {
    const out = {};
    for (const p of meta.params || []) {
      out[p.name] = (node.params && p.name in node.params) ? node.params[p.name] : p.default;
    }
    setVals(out);
  }, [node.id]);

  const update = (k, v) => {
    const next = { ...vals, [k]: v };
    setVals(next);
    onSave(next);
  };

  return (
    <div className="props">
      <div className="props-head">
        <div className="props-icon" style={{ background: color.bg, color: color.fg, borderColor: color.dot }}
             dangerouslySetInnerHTML={{ __html: window.XFLOWS_ICONS[meta.icon] || '' }} />
        <div>
          <div className="props-name">{meta.name}</div>
          <div className="props-cat" style={{ color: color.fg }}>{meta.category}</div>
        </div>
      </div>
      <div className="props-desc">{meta.desc}</div>
      <div className="props-body">
        {(meta.params || []).length === 0 && <div className="empty-mini">No parameters.</div>}
        {(meta.params || []).map(p => (
          <div className="field" key={p.name}>
            <label>
              <span className="field-name">{p.name}</span>
              <span className="field-default">default: {String(p.default)}</span>
            </label>
            {p.type === 'select' && (
              <select value={vals[p.name] ?? p.default} onChange={(e) => update(p.name, e.target.value)}>
                {p.options.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {p.type === 'number' && (
              <input type="number" step={p.step || 1} value={vals[p.name] ?? ''}
                     onChange={(e) => update(p.name, e.target.value === '' ? '' : Number(e.target.value))} />
            )}
            {p.type === 'text' && (
              <input type="text" value={vals[p.name] ?? ''} onChange={(e) => update(p.name, e.target.value)} />
            )}
            {p.type === 'textarea' && (
              <textarea rows={4} value={vals[p.name] ?? ''} onChange={(e) => update(p.name, e.target.value)} />
            )}
            {p.type === 'bool' && (
              <label className="toggle">
                <input type="checkbox" checked={!!vals[p.name]} onChange={(e) => update(p.name, e.target.checked)} />
                <span>{vals[p.name] ? 'True' : 'False'}</span>
              </label>
            )}
            {p.help && <div className="field-help">{p.help}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

window.PropertiesPanel = PropertiesPanel;
