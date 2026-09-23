import { useEffect, useState } from "react";
import {
  CATEGORY_COLORS,
  STATUS_META,
  XFLOWS_ICONS,
  getComponentMeta,
} from "../catalog/catalog-meta";

function PropertiesPanel({ node, onSave }) {
  const meta = getComponentMeta(node.componentId);
  const [vals, setVals] = useState(() => {
    const next = {};
    for (const param of meta?.params || []) {
      next[param.name] =
        node.params && param.name in node.params ? node.params[param.name] : param.default;
    }
    return next;
  });
  const [options, setOptions] = useState(() => ({
    retry: { ...(node.retry || {}), attempts: node.retry?.attempts ?? 3, backoffMs: node.retry?.backoffMs ?? 1000 },
    timeoutS: node.timeoutS ?? 120,
    onError: node.onError || "fail",
  }));

  useEffect(() => {
    const next = {};
    for (const param of meta?.params || []) {
      next[param.name] =
        node.params && param.name in node.params ? node.params[param.name] : param.default;
    }
    setVals(next);
    setOptions({
      retry: { ...(node.retry || {}), attempts: node.retry?.attempts ?? 3, backoffMs: node.retry?.backoffMs ?? 1000 },
      timeoutS: node.timeoutS ?? 120,
      onError: node.onError || "fail",
    });
  }, [node.id, node.params, node.retry, node.timeoutS, node.onError, meta?.params]);

  if (!meta) return null;
  const color = CATEGORY_COLORS[meta.category];
  const status = STATUS_META[meta.status] || STATUS_META.planned;

  const update = (key, value) => {
    const next = { ...vals, [key]: value };
    setVals(next);
    onSave(next, options);
  };

  const updateOption = (key, value) => {
    const nextOptions =
      key === "attempts" || key === "backoffMs"
        ? { ...options, retry: { ...options.retry, [key]: value } }
        : { ...options, [key]: value };
    setOptions(nextOptions);
    onSave(vals, nextOptions);
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
            <span className={`wf-cp-status ${status.className}`}>{status.label}</span>
          </div>
        </div>
      </div>
      <div className="wf-props-desc">{meta.desc}</div>
      {meta.statusNote && <div className="wf-props-note">{meta.statusNote}</div>}
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
      <div className="wf-props-advanced">
        <div className="wf-props-adv-title">Execution options (per node)</div>
        <div className="wf-field">
          <label>
            <span className="wf-field-name">retry.attempts</span>
            <span className="wf-field-default">default: 3</span>
          </label>
          <input
            type="number"
            min={1}
            value={options.retry.attempts ?? ""}
            onChange={(event) =>
              updateOption("attempts", event.target.value === "" ? "" : Number(event.target.value))
            }
          />
        </div>
        <div className="wf-field">
          <label>
            <span className="wf-field-name">retry.backoffMs</span>
            <span className="wf-field-default">default: 1000</span>
          </label>
          <input
            type="number"
            value={options.retry.backoffMs ?? ""}
            onChange={(event) =>
              updateOption("backoffMs", event.target.value === "" ? "" : Number(event.target.value))
            }
          />
        </div>
        <div className="wf-field">
          <label>
            <span className="wf-field-name">timeoutS</span>
            <span className="wf-field-default">default: 120</span>
          </label>
          <input
            type="number"
            value={options.timeoutS ?? ""}
            onChange={(event) =>
              updateOption("timeoutS", event.target.value === "" ? "" : Number(event.target.value))
            }
          />
        </div>
        <div className="wf-field">
          <label>
            <span className="wf-field-name">onError</span>
            <span className="wf-field-default">error edges route failures automatically</span>
          </label>
          <select
            value={options.onError}
            onChange={(event) => updateOption("onError", event.target.value)}
          >
            <option value="fail">fail</option>
            <option value="continue">continue</option>
          </select>
        </div>
      </div>
    </div>
  );
}

export default PropertiesPanel;
