import { useEffect, useState } from "react";
import {
  CATEGORY_COLORS,
  XFLOWS_CATALOG,
  XFLOWS_ICONS,
} from "../catalog/catalog-meta";

function PropertiesPanel({ node, onSave }) {
  const meta = XFLOWS_CATALOG.find((component) => component.id === node.componentId);
  const [vals, setVals] = useState(() => {
    const next = {};
    for (const param of meta?.params || []) {
      next[param.name] =
        node.params && param.name in node.params ? node.params[param.name] : param.default;
    }
    return next;
  });

  useEffect(() => {
    const next = {};
    for (const param of meta?.params || []) {
      next[param.name] =
        node.params && param.name in node.params ? node.params[param.name] : param.default;
    }
    setVals(next);
  }, [node.id, node.params, meta?.params]);

  if (!meta) return null;
  const color = CATEGORY_COLORS[meta.category];

  const update = (key, value) => {
    const next = { ...vals, [key]: value };
    setVals(next);
    onSave(next);
  };

  return (
    <div className="wf-props">
      <div className="wf-props-head">
        <div
          className="wf-props-icon"
          style={{ background: color.bg, color: color.fg, borderColor: color.dot }}
          dangerouslySetInnerHTML={{ __html: XFLOWS_ICONS[meta.icon] || "" }}
        />
        <div>
          <div className="wf-props-name">{meta.name}</div>
          <div className="wf-props-cat" style={{ color: color.fg }}>
            {meta.category}
          </div>
        </div>
      </div>
      <div className="wf-props-desc">{meta.desc}</div>
      <div className="wf-props-body">
        {(meta.params || []).length === 0 && <div className="wf-empty-mini">No parameters.</div>}
        {(meta.params || []).map((param) => (
          <div className="wf-field" key={param.name}>
            <label>
              <span className="wf-field-name">{param.name}</span>
              <span className="wf-field-default">default: {String(param.default)}</span>
            </label>
            {param.type === "select" && (
              <select
                value={vals[param.name] ?? param.default}
                onChange={(event) => update(param.name, event.target.value)}
              >
                {param.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            )}
            {param.type === "number" && (
              <input
                type="number"
                step={param.step || 1}
                value={vals[param.name] ?? ""}
                onChange={(event) =>
                  update(
                    param.name,
                    event.target.value === "" ? "" : Number(event.target.value)
                  )
                }
              />
            )}
            {param.type === "text" && (
              <input
                type="text"
                value={vals[param.name] ?? ""}
                onChange={(event) => update(param.name, event.target.value)}
              />
            )}
            {param.type === "textarea" && (
              <textarea
                rows={4}
                value={vals[param.name] ?? ""}
                onChange={(event) => update(param.name, event.target.value)}
              />
            )}
            {param.type === "bool" && (
              <label className="wf-toggle">
                <input
                  type="checkbox"
                  checked={!!vals[param.name]}
                  onChange={(event) => update(param.name, event.target.checked)}
                />
                <span>{vals[param.name] ? "True" : "False"}</span>
              </label>
            )}
            {param.help && <div className="wf-field-help">{param.help}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

export default PropertiesPanel;
