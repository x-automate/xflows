// Component sidebar — draggable items grouped by category
function ComponentPanel({ onAddNode, query, setQuery }) {
  const cats = {};
  for (const c of window.XFLOWS_CATALOG) {
    if (query && !c.name.toLowerCase().includes(query.toLowerCase())) continue;
    cats[c.category] = cats[c.category] || [];
    cats[c.category].push(c);
  }

  return (
    <div className="component-panel">
      <div className="cp-search">
        <input
          placeholder="Search nodes…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="cp-list">
        {Object.entries(cats).map(([cat, items]) => {
          const color = window.CATEGORY_COLORS[cat];
          return (
            <div className="cp-cat" key={cat}>
              <div className="cp-cat-head">
                <span className="cat-dot" style={{ background: color.dot }} />
                <span>{cat}</span>
                <span className="cp-cat-count">{items.length}</span>
              </div>
              {items.map(c => (
                <div
                  className="cp-item"
                  key={c.id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('component-id', c.id);
                    e.dataTransfer.effectAllowed = 'copy';
                  }}
                  onDoubleClick={() => onAddNode(c.id)}
                  title={c.desc}
                  style={{ borderLeftColor: color.dot }}
                >
                  <div className="cp-item-icon" style={{ background: color.bg, color: color.fg, borderColor: color.dot }}
                       dangerouslySetInnerHTML={{ __html: window.XFLOWS_ICONS[c.icon] || '' }} />
                  <div className="cp-item-body">
                    <div className="cp-item-name">{c.name}</div>
                    <div className="cp-item-desc">{c.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
        {Object.keys(cats).length === 0 && (
          <div className="empty-mini">No nodes match "{query}".</div>
        )}
      </div>
    </div>
  );
}

window.ComponentPanel = ComponentPanel;
