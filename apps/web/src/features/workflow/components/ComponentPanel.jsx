import {
  CATEGORY_COLORS,
  STATUS_META,
  XFLOWS_CATALOG,
  XFLOWS_ICONS,
  isPlaceable,
} from "../catalog/catalog-meta";

function matchesQuery(component, query) {
  if (!query) return true;
  const needle = query.toLowerCase();
  return [component.name, component.id, component.category, component.desc].some(
    (field) => String(field || "").toLowerCase().includes(needle)
  );
}

function ComponentPanel({ onAddNode, query, setQuery }) {
  const categories = {};
  for (const component of XFLOWS_CATALOG) {
    if (!matchesQuery(component, query)) continue;
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
              {items.map((component) => {
                const placeable = isPlaceable(component);
                const status = STATUS_META[component.status] || STATUS_META.planned;
                const itemClasses = `wf-cp-item${placeable ? "" : " wf-cp-item-planned"}`;
                return (
                  <div
                    className={itemClasses}
                    key={component.id}
                    draggable={placeable}
                    onDragStart={(event) => {
                      if (!placeable) {
                        event.preventDefault();
                        return;
                      }
                      event.dataTransfer.setData("component-id", component.id);
                      event.dataTransfer.effectAllowed = "copy";
                    }}
                    onDoubleClick={() => {
                      if (!placeable) return;
                      onAddNode(component.id);
                    }}
                    title={placeable ? component.desc : `${component.desc} — ${component.statusNote || "not implemented yet"}`}
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
                      <div className="wf-cp-item-name">
                        {component.name}
                        <span className={`wf-cp-status ${status.className}`}>{status.label}</span>
                      </div>
                      <div className="wf-cp-item-desc">{placeable ? component.desc : component.statusNote || component.desc}</div>
                    </div>
                  </div>
                );
              })}
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
