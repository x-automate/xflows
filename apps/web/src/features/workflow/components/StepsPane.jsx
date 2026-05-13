import { useEffect, useMemo, useRef, useState } from "react";
import { CATEGORY_COLORS, getComponentMeta } from "../catalog/catalog-meta";
import { useWorkflowValidation } from "../hooks/useWorkflowValidation";
import PropertiesPanel from "./PropertiesPanel";

function StepsPane({
  nodes,
  edges,
  selected,
  onSelect,
  onOpenParams,
  onSaveParams,
  onDelete,
  onRun,
  runState,
}) {
  const validation = useWorkflowValidation(nodes, edges);
  const [tab, setTab] = useState("properties");
  const selectedNode =
    selected && !String(selected).startsWith("e_")
      ? nodes.find((node) => node.id === selected)
      : null;

  useEffect(() => {
    if (selectedNode) setTab("properties");
  }, [selectedNode]);

  const orderedNodes = useMemo(() => {
    if (!validation.order?.length) return nodes;
    return validation.order
      .map((id) => nodes.find((node) => node.id === id))
      .filter(Boolean);
  }, [validation.order, nodes]);

  return (
    <aside className="wf-right-pane">
      <div className="wf-right-tabs">
        <button
          className={tab === "properties" ? "active" : ""}
          onClick={() => setTab("properties")}
        >
          Properties
        </button>
        <button className={tab === "steps" ? "active" : ""} onClick={() => setTab("steps")}>
          Steps <span className="wf-badge">{nodes.length}</span>
        </button>
        <button className={tab === "test" ? "active" : ""} onClick={() => setTab("test")}>
          Test
          {runState.events.some((event) => event.type === "error") && (
            <span className="wf-badge err">!</span>
          )}
        </button>
        <button
          className={tab === "validation" ? "active" : ""}
          onClick={() => setTab("validation")}
        >
          Validation
          {validation.errors.length > 0 && (
            <span className="wf-badge err">{validation.errors.length}</span>
          )}
        </button>
      </div>

      {tab === "properties" && (
        <div className="wf-pane-body">
          {selectedNode ? (
            <PropertiesPanel
              node={selectedNode}
              onSave={(params) => onSaveParams(selectedNode.id, params)}
            />
          ) : (
            <div className="wf-empty">
              <div className="wf-empty-title">No node selected</div>
              <div className="wf-empty-sub">Click a node on the canvas to configure it.</div>
            </div>
          )}
        </div>
      )}

      {tab === "steps" && (
        <div className="wf-pane-body">
          {orderedNodes.length === 0 && (
            <div className="wf-empty">
              <div className="wf-empty-title">No nodes yet</div>
              <div className="wf-empty-sub">Drag a node from the left onto the canvas.</div>
            </div>
          )}
          <ol className="wf-step-list">
            {orderedNodes.map((node, index) => {
              const meta = getComponentMeta(node.componentId);
              if (!meta) return null;
              const color = CATEGORY_COLORS[meta.category];
              return (
                <li
                  key={node.id}
                  className={`wf-step-row${selected === node.id ? " selected" : ""}`}
                  onClick={() => onSelect(node.id)}
                >
                  <div className="wf-step-num">{index + 1}</div>
                  <div className="wf-step-main">
                    <div className="wf-step-head">
                      <span className="wf-cat-dot" style={{ background: color.dot }} />
                      <span className="wf-step-name">{meta.name}</span>
                      <span className="wf-step-cat">{meta.category}</span>
                    </div>
                    <div className="wf-step-params">
                      {(meta.params || []).slice(0, 3).map((param) => {
                        const value =
                          node.params && param.name in node.params
                            ? node.params[param.name]
                            : param.default;
                        if (value === "" || value === null || value === undefined) return null;
                        return (
                          <span className="wf-param-pill" key={param.name}>
                            <span className="wf-pk">{param.name}</span>
                            <span className="wf-pv">{String(value).slice(0, 24)}</span>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                  <div className="wf-step-actions">
                    <button
                      title="Configure"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenParams(node.id);
                      }}
                    >
                      ⚙
                    </button>
                    <button
                      title="Delete"
                      onClick={(event) => {
                        event.stopPropagation();
                        onDelete(node.id);
                      }}
                    >
                      ✕
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {tab === "test" && (
        <TestPanel
          nodes={nodes}
          runState={runState}
          onRun={onRun}
          canRun={validation.errors.length === 0}
          validationErrors={validation.errors}
        />
      )}

      {tab === "validation" && (
        <div className="wf-pane-body">
          {validation.errors.length === 0 ? (
            <div className="wf-valid-ok">
              <div className="wf-ok-mark">✓</div>
              <div className="wf-ok-title">Workflow is valid</div>
              <div className="wf-ok-sub">{nodes.length} nodes - ready to run</div>
            </div>
          ) : (
            <ul className="wf-valid-list">
              {validation.errors.map((error, idx) => (
                <li key={idx} className="wf-valid-row err">
                  <span className="wf-bullet">!</span>
                  <span>{error}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}

function TestPanel({
  nodes,
  onRun,
  runState,
  canRun,
  validationErrors,
}) {
  const [input, setInput] = useState("What is the capital of France?");
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [runState.events.length]);

  return (
    <div className="wf-pane-body wf-test-body">
      <div className="wf-test-section">
        <div className="wf-test-label">Test input</div>
        <textarea
          className="wf-test-input"
          rows={3}
          placeholder="Type a test message..."
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <div className="wf-test-actions">
          <button
            className={`wf-run-btn${canRun && !runState.running ? "" : " disabled"}`}
            onClick={() => canRun && !runState.running && onRun(input)}
            disabled={!canRun || runState.running}
          >
            {runState.running ? "Running..." : "Run workflow"}
          </button>
        </div>
        {!canRun && validationErrors.length > 0 && (
          <div className="wf-test-warn">Fix validation errors before running.</div>
        )}
      </div>

      <div className="wf-test-section">
        <div className="wf-test-label">Execution trace</div>
        <div className="wf-trace-log" ref={logRef}>
          {runState.events.length === 0 && (
            <div className="wf-empty-mini">No runs yet. Press Run to execute.</div>
          )}
          {runState.events.map((event, idx) => {
            const node = nodes.find((item) => item.id === event.nodeId);
            const meta = node ? getComponentMeta(node.componentId) : null;
            const name = meta?.name || event.nodeId || "-";
            if (event.type === "start") {
              return (
                <div key={idx} className="wf-trace-row">
                  <span className="wf-trace-icon running">
                    <span className="wf-spinner sm" />
                  </span>
                  <span className="wf-trace-name">{name}</span>
                  <span className="wf-trace-msg">started</span>
                </div>
              );
            }
            if (event.type === "success") {
              const provider = event.metadata?.provider;
              const model = event.metadata?.model;
              return (
                <div key={idx} className="wf-trace-row">
                  <span className="wf-trace-icon ok">✓</span>
                  <span className="wf-trace-name">{name}</span>
                  <span className="wf-trace-msg">
                    {event.duration ? `${Math.round(event.duration)}ms` : ""}
                  </span>
                  {(provider || model) && (
                    <div className="wf-trace-output">
                      {provider ? `provider=${provider}` : ""}
                      {provider && model ? " " : ""}
                      {model ? `model=${model}` : ""}
                    </div>
                  )}
                  {event.output != null && (
                    <div className="wf-trace-output">
                      {String(event.output).slice(0, 200)}
                      {String(event.output).length > 200 ? "..." : ""}
                    </div>
                  )}
                </div>
              );
            }
            if (event.type === "error") {
              return (
                <div key={idx} className="wf-trace-row">
                  <span className="wf-trace-icon err">✕</span>
                  <span className="wf-trace-name">{name}</span>
                  <span className="wf-trace-msg err">{event.error || "failed"}</span>
                </div>
              );
            }
            return null;
          })}
        </div>
      </div>

      {runState.finalOutput != null && (
        <div className="wf-test-section">
          <div className="wf-test-label">Final output</div>
          <pre className="wf-final-output">{runState.finalOutput}</pre>
        </div>
      )}
    </div>
  );
}

export default StepsPane;
