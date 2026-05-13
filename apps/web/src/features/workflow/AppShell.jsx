import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createWorkflow,
  getRun,
  startRun,
  streamRunEvents,
  updateProject as updateProjectApi,
} from "../../lib/api/workflowApi";
import { getProject, updateProjectGraph } from "../../lib/projectStore";
import { XFLOWS_CATALOG } from "./catalog/catalog-meta";
import { getUnsupportedComponents } from "./catalog/execution-map";
import { useWorkflowValidation } from "./hooks/useWorkflowValidation";
import Canvas from "./components/Canvas";
import ComponentPanel from "./components/ComponentPanel";
import ParamModal from "./components/ParamModal";
import StepsPane from "./components/StepsPane";
import "./workflow.css";

function uid() {
  return `n_${Math.random().toString(36).slice(2, 9)}`;
}

const STARTER = () => {
  const a = uid();
  const b = uid();
  const llm = uid();
  const provider = uid();
  const d = uid();
  const t = uid();
  return {
    nodes: [
      { id: a, componentId: "Input", x: 60, y: 180, params: {} },
      {
        id: b,
        componentId: "PromptTemplate",
        x: 230,
        y: 180,
        params: {
          template: "Answer concisely:\n\n{input}",
          system: "You are a helpful assistant.",
        },
      },
      {
        id: llm,
        componentId: "LLM",
        x: 420,
        y: 160,
        params: {},
      },
      {
        id: provider,
        componentId: "OpenAIChat",
        parent: llm,
        params: { model: "gpt-4o-mini", temperature: 0.7, max_tokens: 256 },
      },
      { id: d, componentId: "Output", x: 680, y: 180, params: {} },
      {
        id: t,
        componentId: "Tracer",
        x: 420,
        y: 320,
        params: { level: "info", destination: "both" },
      },
    ],
    edges: [
      { id: "e1", source: a, target: b, kind: "data" },
      { id: "e2", source: b, target: llm, kind: "data" },
      { id: "e3", source: llm, target: d, kind: "data" },
      { id: "e4", source: t, target: llm, kind: "config", slot: "tracer" },
    ],
  };
};

function WorkflowAppShell({ projectId, readOnly = false, autoReplay = false, liveRunId = null }) {
  const [{ nodes, edges }, setGraph] = useState(() => {
    const graph = projectId ? getProject(projectId)?.graph : null;
    return graph || STARTER();
  });
  const [selected, setSelected] = useState(null);
  const [editingNode, setEditingNode] = useState(null);
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState({ past: [], future: [] });
  const [toast, setToast] = useState(null);
  const [apiKeys, setApiKeys] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("xflows_keys") || "{}");
    } catch {
      return {};
    }
  });
  const [runState, setRunState] = useState({
    running: false,
    runId: null,
    events: [],
    runStatus: {},
    durations: {},
    activeEdges: {},
    finalOutput: null,
  });
  const validation = useWorkflowValidation(nodes, edges);

  useEffect(() => {
    sessionStorage.setItem("xflows_keys", JSON.stringify(apiKeys));
  }, [apiKeys]);

  useEffect(() => {
    if (projectId && !readOnly) {
      updateProjectGraph(projectId, { nodes, edges });
      const timer = setTimeout(() => {
        updateProjectApi(projectId, { graph: { nodes, edges } }).catch(() => {
          // Local draft remains available if API sync fails.
        });
      }, 500);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [projectId, readOnly, nodes, edges]);

  const flash = (msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 1800);
  };

  const commit = (next) => {
    if (readOnly) return;
    setHistory((current) => ({
      past: [...current.past, { nodes, edges }].slice(-50),
      future: [],
    }));
    setGraph(next);
  };

  const undo = () => {
    if (readOnly) return;
    setHistory((current) => {
      if (!current.past.length) return current;
      const prev = current.past[current.past.length - 1];
      setGraph(prev);
      return {
        past: current.past.slice(0, -1),
        future: [{ nodes, edges }, ...current.future],
      };
    });
  };

  const redo = () => {
    if (readOnly) return;
    setHistory((current) => {
      if (!current.future.length) return current;
      const next = current.future[0];
      setGraph(next);
      return {
        past: [...current.past, { nodes, edges }],
        future: current.future.slice(1),
      };
    });
  };

  const addNodeAt = (componentId, pos, dropTargetId) => {
    if (readOnly) return;
    const meta = XFLOWS_CATALOG.find((component) => component.id === componentId);
    if (!meta) return;
    if (dropTargetId) {
      const container = nodes.find((node) => node.id === dropTargetId);
      const containerMeta =
        container &&
        XFLOWS_CATALOG.find((component) => component.id === container.componentId);
      if (
        containerMeta?.kind === "container" &&
        containerMeta.accepts?.includes(meta.category)
      ) {
        const filteredNodes = nodes.filter((node) => node.parent !== container.id);
        const nestedNode = { id: uid(), componentId, parent: container.id, params: {} };
        commit({ nodes: [...filteredNodes, nestedNode], edges });
        setSelected(nestedNode.id);
        return;
      }
    }
    if (meta.kind === "provider") {
      flash(`Drop ${meta.name} inside an ${meta.requiresContainer} container.`, "err");
      return;
    }
    const node = {
      id: uid(),
      componentId,
      x: pos?.x ?? 200,
      y: pos?.y ?? 200,
      params: {},
    };
    commit({ nodes: [...nodes, node], edges });
    setSelected(node.id);
  };

  const addNodeQuick = (componentId) =>
    addNodeAt(componentId, {
      x: 60 + nodes.length * 30,
      y: 80 + nodes.length * 30,
    });

  const moveNode = (id, pos) => {
    if (readOnly) return;
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === id ? { ...node, ...pos } : node
      ),
    }));
  };

  const connect = (source, target, kind = "data", slot) => {
    if (readOnly) return;
    if (
      edges.some(
        (edge) =>
          edge.source === source &&
          edge.target === target &&
          (edge.kind || "data") === kind &&
          edge.slot === slot
      )
    ) {
      return;
    }
    const edge = { id: `e_${uid()}`, source, target, kind };
    if (slot) edge.slot = slot;
    commit({
      nodes,
      edges: [...edges, edge],
    });
  };

  const deleteSelected = useCallback(() => {
    if (readOnly) return;
    if (!selected) return;
    if (selected.startsWith("e_")) {
      commit({ nodes, edges: edges.filter((edge) => edge.id !== selected) });
    } else {
      const toRemove = new Set([
        selected,
        ...nodes.filter((node) => node.parent === selected).map((node) => node.id),
      ]);
      commit({
        nodes: nodes.filter((node) => !toRemove.has(node.id)),
        edges: edges.filter(
          (edge) => !toRemove.has(edge.source) && !toRemove.has(edge.target)
        ),
      });
    }
    setSelected(null);
  }, [readOnly, selected, nodes, edges]);

  const duplicateSelected = () => {
    if (readOnly) return;
    if (!selected || selected.startsWith("e_")) return;
    const node = nodes.find((item) => item.id === selected);
    if (!node) return;
    const copy = {
      ...node,
      id: uid(),
      x: node.x + 32,
      y: node.y + 32,
      params: { ...node.params },
    };
    commit({ nodes: [...nodes, copy], edges });
    setSelected(copy.id);
  };

  const updateNodeParams = (id, params) => {
    if (readOnly) return;
    commit({
      nodes: nodes.map((node) => (node.id === id ? { ...node, params } : node)),
      edges,
    });
  };

  const clearAll = () => {
    if (readOnly) return;
    if (nodes.length === 0) return;
    if (!window.confirm("Clear the entire canvas?")) return;
    commit({ nodes: [], edges: [] });
    setSelected(null);
  };

  const saveJson = () => {
    const blob = new Blob([JSON.stringify({ nodes, edges }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "workflow.json";
    link.click();
    URL.revokeObjectURL(url);
    flash("Saved workflow.json");
  };

  const loadJson = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        if (Array.isArray(data.nodes) && Array.isArray(data.edges)) {
          commit({ nodes: data.nodes, edges: data.edges });
          flash("Workflow loaded");
        }
      } catch {
        flash("Invalid file", "err");
      }
    };
    reader.readAsText(file);
    event.target.value = "";
  };

  const normalizeEvent = (eventPayload) => {
    if (eventPayload.type === "node_started") {
      return { type: "start", nodeId: eventPayload.nodeId };
    }
    if (eventPayload.type === "node_succeeded") {
      return {
        type: "success",
        nodeId: eventPayload.nodeId,
        duration: eventPayload.payload?.durationMs ?? null,
        output: eventPayload.payload?.output ?? null,
      };
    }
    if (eventPayload.type === "node_failed") {
      return {
        type: "error",
        nodeId: eventPayload.nodeId,
        error: eventPayload.payload?.error ?? "Node failed",
      };
    }
    return null;
  };

  const applyRunEvent = (event) => {
    setRunState((previous) => {
      const existingIdx = previous.events.findIndex(
        (item) => item.nodeId === event.nodeId
      );
      const nextEvents = [...previous.events];
      if (existingIdx >= 0 && event.nodeId) {
        nextEvents[existingIdx] = event;
      } else {
        nextEvents.push(event);
      }
      const next = { ...previous, events: nextEvents };
      if (event.type === "start") {
        next.runStatus = { ...previous.runStatus, [event.nodeId]: "running" };
      } else if (event.type === "success") {
        next.runStatus = { ...previous.runStatus, [event.nodeId]: "success" };
        next.durations = { ...previous.durations, [event.nodeId]: event.duration };
        const order = validation.order || [];
        const idx = order.indexOf(event.nodeId);
        if (idx >= 0 && idx < order.length - 1) {
          const edge = edges.find(
            (item) =>
              (item.kind || "data") === "data" &&
              item.source === event.nodeId &&
              item.target === order[idx + 1]
          );
          if (edge) {
            next.activeEdges = { ...previous.activeEdges, [edge.id]: true };
            setTimeout(() => {
              setRunState((value) => {
                const activeEdges = { ...value.activeEdges };
                delete activeEdges[edge.id];
                return { ...value, activeEdges };
              });
            }, 800);
          }
        }
      } else if (event.type === "error") {
        next.runStatus = { ...previous.runStatus, [event.nodeId]: "error" };
      }
      return next;
    });
  };

  const runWorkflow = async (userInput) => {
    setRunState({
      running: true,
      runId: null,
      events: [],
      runStatus: {},
      durations: {},
      activeEdges: {},
      finalOutput: null,
    });

    try {
      const unsupported = getUnsupportedComponents(nodes);
      if (unsupported.length) {
        throw new Error(
          `Unsupported components for backend execution: ${[
            ...new Set(unsupported),
          ].join(", ")}`
        );
      }
      const workflowId = `wf_web_editor_${Date.now()}`;
      const workflowPayload = {
        id: workflowId,
        name: "Web Editor Workflow",
        description: "Workflow created from migrated web editor",
        nodes,
        edges,
        metadata: { source: "apps/web" },
      };
      await createWorkflow(workflowPayload);
      const run = await startRun(workflowId, userInput);
      setRunState((previous) => ({ ...previous, runId: run.id }));

      const closeStream = streamRunEvents(run.id, (eventPayload) => {
        const mapped = normalizeEvent(eventPayload);
        if (mapped) {
          applyRunEvent(mapped);
        }
        if (eventPayload.type === "run_failed") {
          setRunState((previous) => ({ ...previous, running: false }));
          flash(eventPayload.payload?.error || "Workflow failed", "err");
        }
        if (eventPayload.type === "run_succeeded") {
          setRunState((previous) => ({
            ...previous,
            running: false,
            finalOutput:
              eventPayload.payload?.output ??
              previous.finalOutput,
          }));
        }
      });

      let status = run.status;
      while (status === "queued" || status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        const latest = await getRun(run.id);
        status = latest.status;
        if (status === "succeeded") {
          setRunState((previous) => ({
            ...previous,
            running: false,
            finalOutput: latest.output ?? "",
          }));
          flash("Workflow completed");
        }
        if (status === "failed" || status === "cancelled") {
          setRunState((previous) => ({ ...previous, running: false }));
          flash(latest.error || "Workflow failed", "err");
        }
      }
      closeStream();
    } catch (error) {
      setRunState((previous) => ({ ...previous, running: false }));
      flash(error.message || "Workflow failed", "err");
    }
  };

  const decoratedNodes = useMemo(() => {
    const order = validation.order || [];
    return nodes.map((node) => {
      const idx = order.indexOf(node.id);
      return {
        ...node,
        stepIndex: idx >= 0 ? idx + 1 : null,
        runStatus: runState.runStatus[node.id],
        duration: runState.durations[node.id],
      };
    });
  }, [nodes, validation.order, runState.runStatus, runState.durations]);

  const decoratedEdges = edges.map((edge) => ({
    ...edge,
    activeEdge: !!runState.activeEdges[edge.id],
  }));

  const editing = editingNode ? nodes.find((node) => node.id === editingNode) : null;

  useEffect(() => {
    if (!readOnly || !liveRunId) return undefined;
    setRunState({
      running: true,
      runId: liveRunId,
      events: [],
      runStatus: {},
      durations: {},
      activeEdges: {},
      finalOutput: null,
    });
    const closeStream = streamRunEvents(liveRunId, (eventPayload) => {
      const mapped = normalizeEvent(eventPayload);
      if (mapped) {
        applyRunEvent(mapped);
      }
      if (eventPayload.type === "run_failed") {
        setRunState((previous) => ({ ...previous, running: false }));
      }
      if (eventPayload.type === "run_succeeded") {
        setRunState((previous) => ({
          ...previous,
          running: false,
          finalOutput: eventPayload.payload?.output ?? previous.finalOutput,
        }));
      }
    });
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        try {
          const latest = await getRun(liveRunId);
          if (latest.status === "succeeded" || latest.status === "failed") {
            setRunState((previous) => ({
              ...previous,
              running: false,
              finalOutput: latest.output ?? previous.finalOutput,
            }));
            break;
          }
        } catch {
          break;
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      closeStream();
    };
  }, [readOnly, liveRunId]);

  useEffect(() => {
    if (!autoReplay || liveRunId) return undefined;
    const order = validation.order || [];
    const sequence = order
      .map((id) => nodes.find((node) => node.id === id))
      .filter((node) => {
        if (!node || node.parent) return false;
        const meta = XFLOWS_CATALOG.find(
          (component) => component.id === node.componentId
        );
        return meta?.category !== "Observability";
      });
    if (!sequence.length) return undefined;

    const timers = [];
    setRunState({
      running: true,
      runId: `preview_${Date.now()}`,
      events: [],
      runStatus: {},
      durations: {},
      activeEdges: {},
      finalOutput: null,
    });

    sequence.forEach((node, index) => {
      timers.push(
        window.setTimeout(() => {
          setRunState((previous) => {
            const next = {
              ...previous,
              events: [
                ...previous.events,
                {
                  type: "success",
                  nodeId: node.id,
                  duration: 180 + index * 90,
                  output:
                    node.componentId === "Output"
                      ? "Draft support response generated."
                      : null,
                },
              ],
              runStatus: { ...previous.runStatus, [node.id]: "success" },
              durations: { ...previous.durations, [node.id]: 180 + index * 90 },
            };
            const nextNode = sequence[index + 1];
            if (nextNode) {
              const edge = edges.find(
                (item) =>
                  (item.kind || "data") === "data" &&
                  item.source === node.id &&
                  item.target === nextNode.id
              );
              if (edge) {
                next.activeEdges = { ...previous.activeEdges, [edge.id]: true };
                timers.push(
                  window.setTimeout(() => {
                    setRunState((value) => {
                      const activeEdges = { ...value.activeEdges };
                      delete activeEdges[edge.id];
                      return { ...value, activeEdges };
                    });
                  }, 500)
                );
              }
            } else {
              next.running = false;
              next.finalOutput =
                "Production-ready support response confirmed in live view.";
            }
            return next;
          });
        }, 500 + index * 750)
      );
    });

    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [autoReplay, liveRunId, validation.order, nodes, edges]);

  useEffect(() => {
    const onKey = (event) => {
      const target = event.target;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT"
      ) {
        return;
      }

      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelected();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateSelected();
      } else if ((event.metaKey || event.ctrlKey) && event.key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if (
        (event.metaKey || event.ctrlKey) &&
        (event.key === "y" || (event.key === "z" && event.shiftKey))
      ) {
        event.preventDefault();
        redo();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelected, duplicateSelected, redo, undo]);

  return (
    <div className="wf-app">
      <header className="wf-editor-topbar">
        <div className="wf-editor-brand">
          <span className="wf-editor-brand-mark">X</span>
          <span>
            <span className="wf-editor-brand-name">
              {readOnly ? "XFlows Live View" : "XFlows Workflow Editor"}
            </span>
            <span className="wf-editor-brand-sub">
              {readOnly ? "interactive execution playback" : "visual agentic builder"}
            </span>
          </span>
        </div>
        {!readOnly && (
          <div className="wf-topbar-actions">
            <button className="wf-tb-btn" onClick={undo} disabled={!history.past.length}>
              Undo
            </button>
            <button className="wf-tb-btn" onClick={redo} disabled={!history.future.length}>
              Redo
            </button>
            <label className="wf-tb-btn">
              Load
              <input type="file" accept="application/json" onChange={loadJson} hidden />
            </label>
            <button className="wf-tb-btn" onClick={saveJson}>
              Save
            </button>
            <button className="wf-tb-btn" onClick={clearAll}>
              Clear
            </button>
          </div>
        )}
      </header>

      <div className={`wf-main${readOnly ? " wf-main-view" : ""}`}>
        <div className="wf-left-half">
          {!readOnly && (
            <ComponentPanel onAddNode={addNodeQuick} query={query} setQuery={setQuery} />
          )}
          <div className="wf-canvas-host">
            <Canvas
              nodes={decoratedNodes}
              edges={decoratedEdges}
              selected={selected}
              onSelect={setSelected}
              onNodeMove={moveNode}
              onNodeAdd={addNodeAt}
              onConnect={connect}
              onDelete={(id) => {
                setSelected(id);
                setTimeout(deleteSelected, 0);
              }}
              onOpenParams={(id) => setEditingNode(id)}
            />
          </div>
        </div>
        {!readOnly && (
          <StepsPane
            nodes={nodes}
            edges={edges}
            selected={selected}
            onSelect={setSelected}
            onOpenParams={(id) => setEditingNode(id)}
            onSaveParams={updateNodeParams}
            onDelete={(id) => {
              setSelected(id);
              setTimeout(deleteSelected, 0);
            }}
            onRun={runWorkflow}
            runState={runState}
            apiKeys={apiKeys}
            setApiKeys={setApiKeys}
          />
        )}
      </div>

      {editing && !readOnly && (
        <ParamModal
          node={editing}
          onClose={() => setEditingNode(null)}
          onSave={(params) => updateNodeParams(editing.id, params)}
        />
      )}
      {toast && <div className={`wf-toast ${toast.kind}`}>{toast.msg}</div>}
    </div>
  );
}

export default WorkflowAppShell;
