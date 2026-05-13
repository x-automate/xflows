import { useEffect, useState } from "react";
import { CATEGORY_COLORS, XFLOWS_CATALOG } from "../catalog/catalog-meta";

function ParamModal({ node, onClose, onSave }) {
  const meta = XFLOWS_CATALOG.find((component) => component.id === node.componentId);
  const [vals, setVals] = useState(() => {
    const next = {};
    for (const param of meta.params) {
      next[param.name] =
        node.params && param.name in node.params ? node.params[param.name] : param.default;
    }
    return next;
  });

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const setParam = (key, value) =>
    setVals((previous) => ({ ...previous, [key]: value }));
  const color = CATEGORY_COLORS[meta.category];

  return (
    <div className="wf-modal-backdrop" onClick={onClose}>
      <div className="wf-modal" onClick={(event) => event.stopPropagation()}>
        <div className="wf-modal-head">
          <div className="wf-modal-title">
            <span className="wf-cat-dot" style={{ background: color.dot }} />
            <span>{meta.name}</span>
            <span className="wf-modal-mod">{meta.category}</span>
          </div>
          <button className="wf-x-btn" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="wf-modal-desc">{meta.desc}</div>
        <div className="wf-modal-body">
          {meta.params.length === 0 && (
            <div className="wf-empty-mini">No parameters to configure.</div>
          )}
          {meta.params.map((param) => (
            <div className="wf-field" key={param.name}>
              <label>
                <span className="wf-field-name">{param.name}</span>
                <span className="wf-field-default">
                  default: {String(param.default).slice(0, 30)}
                </span>
              </label>
              {param.type === "select" && (
                <select
                  value={vals[param.name] ?? param.default}
                  onChange={(event) => setParam(param.name, event.target.value)}
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
                    setParam(
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
                  onChange={(event) => setParam(param.name, event.target.value)}
                />
              )}
              {param.type === "textarea" && (
                <textarea
                  rows={5}
                  value={vals[param.name] ?? ""}
                  onChange={(event) => setParam(param.name, event.target.value)}
                />
              )}
              {param.type === "bool" && (
                <label className="wf-toggle">
                  <input
                    type="checkbox"
                    checked={!!vals[param.name]}
                    onChange={(event) => setParam(param.name, event.target.checked)}
                  />
                  <span>{vals[param.name] ? "True" : "False"}</span>
                </label>
              )}
              {param.help && <div className="wf-field-help">{param.help}</div>}
            </div>
          ))}
        </div>
        <div className="wf-modal-foot">
          <button className="wf-btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="wf-btn-primary"
            onClick={() => {
              onSave(vals);
              onClose();
            }}
          >
            Save parameters
          </button>
        </div>
      </div>
    </div>
  );
}

export default ParamModal;
