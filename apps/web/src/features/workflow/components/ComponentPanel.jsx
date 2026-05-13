import {
  CATEGORY_COLORS,
  XFLOWS_CATALOG,
  XFLOWS_ICONS,
} from "../catalog/catalog-meta";

function ComponentPanel({ onAddNode, query, setQuery }) {
  const categories = {};
  for (const component of XFLOWS_CATALOG) {
    if (query && !component.name.toLowerCase().includes(query.toLowerCase())) continue;
    categories[component.category] = categories[component.category] || [];
    categories[component.category].push(component);
  }

  return (
    <div className="wf-component-panel">
      <div className="wf-cp-search">
        <input
          placeholder="Search nodes..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="wf-cp-list">
        {Object.entries(categories).map(([category, items]) => {
          const color = CATEGORY_COLORS[category];
          return (
            <div className="wf-cp-cat" key={category}>
              <div className="wf-cp-cat-head">
                <span className="wf-cat-dot" style={{ background: color.dot }} />
                <span>{category}</span>
                <span className="wf-cp-cat-count">{items.length}</span>
              </div>
              {items.map((component) => (
                <div
                  className="wf-cp-item"
                  key={component.id}
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData("component-id", component.id);
                    event.dataTransfer.effectAllowed = "copy";
                  }}
                  onDoubleClick={() => onAddNode(component.id)}
                  title={component.desc}
                  style={{ borderLeftColor: color.dot }}
                >
                  <div
                    className="wf-cp-item-icon"
                    style={{
                      background: color.bg,
                      color: color.fg,
                      borderColor: color.dot,
                    }}
                    dangerouslySetInnerHTML={{
                      __html: XFLOWS_ICONS[component.icon] || "",
                    }}
                  />
                  <div className="wf-cp-item-body">
                  <div className="wf-cp-item-name">{component.name}</div>
                  <div className="wf-cp-item-desc">{component.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
        {Object.keys(categories).length === 0 && (
          <div className="wf-empty-mini">No nodes match "{query}".</div>
        )}
      </div>
    </div>
  );
}

export default ComponentPanel;
