// @vitest-environment jsdom
import { StrictMode, act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { XFLOWS_CATALOG, getComponentMeta } from "../catalog/catalog-meta";
import {
  hasDataOut,
  hasErrorOut,
  isAuxOnly,
  nodeOriginForPort,
} from "../catalog/port-model";
import Canvas from "./Canvas";

/**
 * What the canvas actually renders.
 *
 * The catalog-level tests kept passing while every error bubble was invisible:
 * a `.wf-port` rule declared after `.wf-port-error-out` won the cascade and
 * parked the error port on top of the data port, 20px away from the edge that
 * claimed to leave it. Positions are inline now, so the rendered bubble and
 * the rendered wire can be compared here without a browser.
 */

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container;
let root;
/** jsdom has no layout, so the canvas's hit test is fed explicitly. */
let hitTarget = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  hitTarget = null;
  document.elementFromPoint = () => hitTarget;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const noop = () => {};

function render(graph) {
  act(() => {
    root.render(
      createElement(
        StrictMode,
        null,
        createElement(Canvas, {
          nodes: graph.nodes,
          edges: graph.edges || [],
          selected: null,
          onSelect: noop,
          onNodeMove: noop,
          onNodeAdd: noop,
          onConnect: noop,
          onConnectNew: noop,
          onDelete: noop,
          onOpenParams: noop,
          onUpdateEdge: noop,
          onDeleteEdge: noop,
          ...(graph.props || {}),
        })
      )
    );
  });
}

/** The centre of a rendered bubble, as the canvas positioned it. */
function portAt(nodeId, port, slot) {
  const selector = slot
    ? `[data-node-id="${nodeId}"][data-port="${port}"][data-slot="${slot}"]`
    : `[data-node-id="${nodeId}"][data-port="${port}"]`;
  const el = container.querySelector(selector);
  if (!el) return null;
  return { x: parseFloat(el.style.left), y: parseFloat(el.style.top) };
}

/** The node element carries `data-node-id` too, so ask for bubbles only. */
const portsOf = (nodeId) =>
  [...container.querySelectorAll(`[data-node-id="${nodeId}"][data-port]`)].map(
    (el) => el.dataset.port
  );

/** Both ends of a rendered cubic edge: "M x y C ax ay, bx by, x2 y2". */
function edgeEnds(edgeIndex = 0) {
  const path = container.querySelectorAll("path.wf-edge")[edgeIndex];
  const numbers = path.getAttribute("d").match(/-?\d+(\.\d+)?/g).map(Number);
  return {
    start: { x: numbers[0], y: numbers[1] },
    end: { x: numbers[6], y: numbers[7] },
    className: path.getAttribute("class"),
  };
}

const placed = XFLOWS_CATALOG.map((component, index) => ({
  id: `n${index}`,
  componentId: component.id,
  x: (index % 6) * 260,
  y: Math.floor(index / 6) * 180,
  params: {},
}));

describe("every node renders both output bubbles", () => {
  it("renders a data bubble and an error bubble on every executing node", () => {
    render({ nodes: placed });
    for (const node of placed) {
      const meta = getComponentMeta(node.componentId);
      if (isAuxOnly(meta)) continue;
      expect(
        portAt(node.id, "error-out"),
        `${node.componentId} renders no error bubble`
      ).not.toBeNull();
      if (hasDataOut(meta)) {
        expect(
          portAt(node.id, "out"),
          `${node.componentId} renders no data bubble`
        ).not.toBeNull();
      }
    }
  });

  it("never stacks the error bubble on top of the data bubble", () => {
    render({ nodes: placed });
    for (const node of placed) {
      const data = portAt(node.id, "out");
      const error = portAt(node.id, "error-out");
      if (!data || !error) continue;
      expect(error.x, `${node.componentId}: both outputs share the right edge`).toBe(data.x);
      expect(
        error.y - data.y,
        `${node.componentId}: the error bubble is hidden under the data bubble`
      ).toBeGreaterThan(10);
    }
  });

  it("marks the two bubbles apart for the eye as well as the pointer", () => {
    render({ nodes: placed });
    const data = container.querySelector('[data-port="out"]');
    const error = container.querySelector('[data-port="error-out"]');
    expect(data.className).toContain("wf-port-out");
    expect(error.className).toContain("wf-port-error-out");
    expect(error.getAttribute("title")).toMatch(/error/i);
    expect(data.getAttribute("title")).toMatch(/data/i);
  });

  it("gives the terminal Output an error bubble and no data bubble", () => {
    const output = placed.find((node) => node.componentId === "Output");
    render({ nodes: placed });
    expect(portsOf(output.id)).toEqual(["in", "error-out"]);
  });

  it("gives a trigger both outputs and no input", () => {
    const trigger = placed.find((node) => node.componentId === "Webhook");
    render({ nodes: placed });
    expect(portsOf(trigger.id)).toEqual(["out", "error-out"]);
  });

  it("gives an aux node a config bubble instead of data bubbles", () => {
    const aux = placed.find((node) => node.componentId === "LangfuseTracer");
    render({ nodes: placed });
    expect(portsOf(aux.id)).toEqual(["config-out"]);
  });

  it("renders a bubble per config slot on a container", () => {
    const container_ = placed.find((node) => node.componentId === "LLM");
    render({ nodes: placed });
    expect(portsOf(container_.id)).toEqual([
      "in",
      "out",
      "error-out",
      "config-in",
      "config-in",
      "config-in",
    ]);
  });

  it("leaves a nested provider's ports to its container", () => {
    render({
      nodes: [
        { id: "llm", componentId: "LLM", x: 0, y: 0 },
        { id: "prov", componentId: "OpenAIChat", parent: "llm" },
      ],
    });
    expect(portsOf("prov")).toEqual([]);
  });
});

describe("edges are drawn on the bubbles they leave and land on", () => {
  const nodes = [
    { id: "in", componentId: "Input", x: 40, y: 200 },
    { id: "llm", componentId: "LLM", x: 320, y: 140 },
    { id: "log", componentId: "ErrorLog", x: 640, y: 320 },
    { id: "out", componentId: "Output", x: 640, y: 120 },
    { id: "tracer", componentId: "LangfuseTracer", x: 300, y: 420 },
  ];

  it("starts a data edge on the data bubble and ends it on the input bubble", () => {
    render({
      nodes,
      edges: [{ id: "e1", source: "in", target: "llm", kind: "data" }],
    });
    const { start, end, className } = edgeEnds();
    expect(className).not.toContain("error");
    expect(start).toEqual(portAt("in", "out"));
    expect(end).toEqual(portAt("llm", "in"));
  });

  it("starts an error edge on the error bubble, not the data bubble", () => {
    render({
      nodes,
      edges: [{ id: "e1", source: "llm", target: "log", kind: "error" }],
    });
    const { start, end, className } = edgeEnds();
    expect(className).toContain("error");
    expect(start).toEqual(portAt("llm", "error-out"));
    expect(start).not.toEqual(portAt("llm", "out"));
    expect(end).toEqual(portAt("log", "in"));
  });

  it("starts an error edge out of the terminal Output on its error bubble", () => {
    render({
      nodes,
      edges: [{ id: "e1", source: "out", target: "log", kind: "error" }],
    });
    expect(edgeEnds().start).toEqual(portAt("out", "error-out"));
  });

  it("lands a config edge on the slot bubble it names", () => {
    render({
      nodes,
      edges: [{ id: "e1", source: "tracer", target: "llm", kind: "config", slot: "tracer" }],
    });
    const { start, end } = edgeEnds();
    expect(start).toEqual(portAt("tracer", "config-out"));
    expect(end).toEqual(portAt("llm", "config-in", "tracer"));
    expect(end).not.toEqual(portAt("llm", "config-in", "memory"));
  });

  it("treats an edge with no kind as a data edge", () => {
    render({ nodes, edges: [{ id: "e1", source: "in", target: "llm" }] });
    expect(edgeEnds().start).toEqual(portAt("in", "out"));
  });

  it("keeps every edge on its bubbles after the source node moves", () => {
    const moved = nodes.map((node) =>
      node.id === "llm" ? { ...node, x: 480, y: 60 } : node
    );
    render({
      nodes: moved,
      edges: [
        { id: "e1", source: "in", target: "llm", kind: "data" },
        { id: "e2", source: "llm", target: "log", kind: "error" },
      ],
    });
    expect(edgeEnds(0).end).toEqual(portAt("llm", "in"));
    expect(edgeEnds(1).start).toEqual(portAt("llm", "error-out"));
  });

  it("draws every catalog node's edges on its own bubbles", () => {
    const edges = placed
      .filter((node) => hasErrorOut(getComponentMeta(node.componentId)))
      .map((node, index) => ({
        id: `e${index}`,
        source: node.id,
        target: placed.find((item) => item.componentId === "ErrorLog").id,
        kind: "error",
      }))
      .filter((edge) => edge.source !== edge.target);
    render({ nodes: placed, edges });
    edges.forEach((edge, index) => {
      expect(edgeEnds(index).start, `${edge.source} error edge`).toEqual(
        portAt(edge.source, "error-out")
      );
    });
  });
});

describe("dragging a wire", () => {
  const nodes = [
    { id: "llm", componentId: "LLM", x: 100, y: 100 },
    { id: "log", componentId: "ErrorLog", x: 500, y: 300 },
  ];

  const mouseDown = (el) =>
    act(() => {
      el.dispatchEvent(
        new window.MouseEvent("mousedown", { bubbles: true, clientX: 0, clientY: 0 })
      );
    });

  /** The rubber-band wire: the only stroked path drawn straight on the svg. */
  const pendingWire = () =>
    container.querySelector("svg.wf-edges > path[stroke-dasharray]");

  it("draws the pending wire from the bubble it was started on", () => {
    render({ nodes });
    mouseDown(container.querySelector('[data-node-id="llm"][data-port="error-out"]'));
    const pending = pendingWire();
    const numbers = pending.getAttribute("d").match(/-?\d+(\.\d+)?/g).map(Number);
    expect({ x: numbers[0], y: numbers[1] }).toEqual(portAt("llm", "error-out"));
    expect(pending.getAttribute("stroke")).toBe("#dc2626");
  });

  it("draws a data wire from the data bubble in the data colour", () => {
    render({ nodes });
    mouseDown(container.querySelector('[data-node-id="llm"][data-port="out"]'));
    const pending = pendingWire();
    const numbers = pending.getAttribute("d").match(/-?\d+(\.\d+)?/g).map(Number);
    expect({ x: numbers[0], y: numbers[1] }).toEqual(portAt("llm", "out"));
    expect(pending.getAttribute("stroke")).toBe("#3b82f6");
  });
});

describe("pulling a wire out of an input bubble", () => {
  const nodes = [
    { id: "in", componentId: "Input", x: 40, y: 200 },
    { id: "prompt", componentId: "PromptTemplate", x: 260, y: 200 },
    { id: "llm", componentId: "LLM", x: 520, y: 180 },
    { id: "out", componentId: "Output", x: 820, y: 200 },
  ];

  const at = (el, type, x, y) =>
    act(() => {
      el.dispatchEvent(
        new window.MouseEvent(type, { bubbles: true, clientX: x, clientY: y })
      );
    });

  const wrap = () => container.querySelector(".wf-canvas-wrap");
  const bubble = (nodeId, port) =>
    container.querySelector(`[data-node-id="${nodeId}"][data-port="${port}"]`);
  const pendingWire = () =>
    container.querySelector("svg.wf-edges > path[stroke-dasharray]");
  const menu = () => container.querySelector(".wf-connect-menu");
  const rows = () => [...container.querySelectorAll(".wf-connect-row")];
  const rowNamed = (name) =>
    rows().find((row) => row.querySelector(".wf-connect-row-name").textContent === name);

  /** Pull a wire from a bubble and let go at (x, y) over `hit`. */
  const pull = (nodeId, port, { x = 600, y = 420, hit = null } = {}) => {
    at(bubble(nodeId, port), "mousedown", 10, 10);
    at(wrap(), "mousemove", x, y);
    hitTarget = hit;
    at(wrap(), "mouseup", x, y);
  };

  it("draws a solid-path data wire ending on the input bubble it came from", () => {
    render({ nodes });
    at(bubble("llm", "in"), "mousedown", 10, 10);
    const numbers = pendingWire().getAttribute("d").match(/-?\d+(\.\d+)?/g).map(Number);
    // The held end is the *target*, so it is where the path ends, not starts.
    expect({ x: numbers[6], y: numbers[7] }).toEqual(portAt("llm", "in"));
    expect(pendingWire().getAttribute("stroke")).toBe("#3b82f6");
    expect(pendingWire().dataset.kind).toBe("data");
  });

  it("connects to the data output of the node it is dropped on", () => {
    const calls = [];
    render({ nodes, props: { onConnect: (...args) => calls.push(args) } });
    pull("llm", "in", { hit: bubble("prompt", "out") });
    expect(calls).toEqual([["prompt", "llm", "data", undefined]]);
  });

  it("becomes an error edge when dropped on a red output bubble", () => {
    const calls = [];
    render({ nodes, props: { onConnect: (...args) => calls.push(args) } });
    pull("llm", "in", { hit: bubble("prompt", "error-out") });
    expect(calls).toEqual([["prompt", "llm", "error", undefined]]);
  });

  it("connects to a node dropped anywhere on its body", () => {
    const calls = [];
    render({ nodes, props: { onConnect: (...args) => calls.push(args) } });
    const body = container.querySelector('.wf-node[data-node-id="prompt"]');
    pull("llm", "in", { hit: body });
    expect(calls).toEqual([["prompt", "llm", "data", undefined]]);
  });

  it("opens the connect menu when it is let go over empty canvas", () => {
    render({ nodes });
    expect(menu()).toBeNull();
    pull("llm", "in");
    expect(menu()).not.toBeNull();
    expect(menu().textContent).toContain("into");
    expect(menu().querySelector(".wf-connect-kind").textContent).toBe("data");
  });

  it("keeps the wire on screen while the menu decides", () => {
    render({ nodes });
    pull("llm", "in", { x: 600, y: 420 });
    expect(pendingWire()).not.toBeNull();
    expect(pendingWire().getAttribute("class")).toContain("held");
  });

  it("does not open the menu for a click that never pulled a wire", () => {
    render({ nodes });
    at(bubble("llm", "in"), "mousedown", 10, 10);
    at(wrap(), "mouseup", 11, 11);
    expect(menu()).toBeNull();
  });

  it("offers only the nodes that can feed this input", () => {
    render({ nodes });
    pull("llm", "in");
    const names = rows().map((row) => row.querySelector(".wf-connect-row-name").textContent);
    expect(names).toContain("Input");
    expect(names).toContain("Prompt");
    // The terminal Output has no data output to offer.
    expect(names.slice(0, 2)).not.toContain("Output");
  });

  it("connects to a node picked from the menu, wired the way it was pulled", () => {
    const calls = [];
    render({ nodes, props: { onConnect: (...args) => calls.push(args) } });
    pull("llm", "in");
    act(() => rowNamed("Prompt").click());
    expect(calls).toEqual([["prompt", "llm", "data", undefined]]);
    expect(menu()).toBeNull();
  });

  it("creates a node from the menu and drops it on the wire's loose end", () => {
    const created = [];
    render({ nodes, props: { onConnectNew: (...args) => created.push(args) } });
    pull("llm", "in", { x: 610, y: 430 });
    act(() => rowNamed("Error Log").click());
    expect(created).toHaveLength(1);
    const [componentId, origin, link] = created[0];
    expect(componentId).toBe("ErrorLog");
    // The new node's data output lands exactly where the wire was let go.
    expect(origin).toEqual(nodeOriginForPort({ x: 610, y: 430 }, getComponentMeta("ErrorLog"), "out"));
    expect(link).toEqual({
      anchorId: "llm",
      direction: "reverse",
      kind: "data",
      slot: undefined,
    });
  });

  it("closes on Escape without connecting", () => {
    const calls = [];
    render({ nodes, props: { onConnect: (...args) => calls.push(args) } });
    pull("llm", "in");
    act(() => {
      window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(menu()).toBeNull();
    expect(calls).toEqual([]);
  });

  it("closes when the canvas behind it is clicked", () => {
    render({ nodes });
    pull("llm", "in");
    act(() => {
      container
        .querySelector(".wf-connect-backdrop")
        .dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
    });
    expect(menu()).toBeNull();
  });

  it("opens the same menu for a wire pulled forward out of an output", () => {
    render({ nodes });
    pull("prompt", "out");
    expect(menu().textContent).toContain("from");
    const names = rows().map((row) => row.querySelector(".wf-connect-row-name").textContent);
    expect(names).toContain("LLM");
    expect(names).toContain("Output");
  });

  it("carries the error kind into the menu when pulled from the red bubble", () => {
    render({ nodes });
    pull("prompt", "error-out");
    expect(menu().querySelector(".wf-connect-kind").textContent).toBe("error");
    expect(menu().querySelector(".wf-connect-kind").className).toContain("error");
  });

  it("names the slot when a wire is pulled out of a config bubble", () => {
    render({ nodes });
    pull("llm", "config-in");
    expect(menu().textContent).toContain("tracer");
    const names = rows().map((row) => row.querySelector(".wf-connect-row-name").textContent);
    expect(names).toContain("Langfuse");
    expect(names).not.toContain("Prompt");
  });
});
