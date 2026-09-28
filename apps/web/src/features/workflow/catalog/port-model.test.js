import { describe, expect, it } from "vitest";
import { XFLOWS_CATALOG, canSourceConfigEdge, getComponentMeta } from "./catalog-meta.js";
import { checkConnection } from "./connection-rules.js";
import {
  CONT_H,
  CONT_W,
  ERROR_PORT_DROP,
  NODE_H,
  NODE_W,
  hasConfigOut,
  hasDataIn,
  hasDataOut,
  hasErrorOut,
  isAuxOnly,
  portsForNode,
  sizeFor,
  sourcePortPos,
  targetPortPos,
} from "./port-model.js";

/**
 * The port model the canvas renders, asserted against the catalog.
 *
 * These predicates are imported, not restated: the previous version of this
 * file re-derived them locally, so it went on passing while the rendered error
 * bubble sat hidden underneath the data bubble.
 */
const nodeOf = (componentId, x = 100, y = 60) => ({ id: `n_${componentId}`, componentId, x, y });
const portsOf = (componentId) => portsForNode(nodeOf(componentId));
const portKinds = (componentId) => portsOf(componentId).map((port) => port.port);

describe("every node offers both output bubbles", () => {
  it("pairs a data output with an error output on every executing node", () => {
    for (const component of XFLOWS_CATALOG) {
      if (!hasDataOut(component)) continue;
      expect(
        hasErrorOut(component),
        `${component.id} has a data output but no error output`
      ).toBe(true);
    }
  });

  it("renders both bubbles for every node that runs in the data flow", () => {
    for (const component of XFLOWS_CATALOG.filter((item) => !isAuxOnly(item))) {
      const kinds = portKinds(component.id);
      expect(kinds, `${component.id} must offer an error output`).toContain("error-out");
      if (component.kind !== "output") {
        expect(kinds, `${component.id} must offer a data output`).toContain("out");
      }
    }
  });

  it("gives the terminal Output an error output but no data output", () => {
    const output = getComponentMeta("Output");
    expect(hasDataIn(output)).toBe(true);
    expect(hasDataOut(output), "Output is a sink — nothing runs after it").toBe(false);
    expect(hasErrorOut(output), "Output still executes, so it can still fail").toBe(true);
    expect(portKinds("Output")).toEqual(["in", "error-out"]);
  });

  it("gives triggers an error output but no data input", () => {
    for (const id of ["Input", "Webhook", "XWSEventTrigger"]) {
      const meta = getComponentMeta(id);
      expect(meta.kind, `${id} should be an input kind`).toBe("input");
      expect(hasDataIn(meta), `${id} should take no data input`).toBe(false);
      expect(hasDataOut(meta)).toBe(true);
      expect(hasErrorOut(meta), `${id} should be able to route its failures`).toBe(true);
      expect(portKinds(id)).toEqual(["out", "error-out"]);
    }
  });

  it("gives aux nodes a config port instead of data ports", () => {
    for (const component of XFLOWS_CATALOG.filter((item) => item.kind === "aux")) {
      expect(hasDataIn(component), `${component.id} should have no data input`).toBe(false);
      expect(hasDataOut(component), `${component.id} should have no data output`).toBe(false);
      expect(hasErrorOut(component), `${component.id} does not run on its own`).toBe(false);
      expect(hasConfigOut(component)).toBe(canSourceConfigEdge(component));
      expect(
        portKinds(component.id),
        `${component.id} is aux so it must offer a config port`
      ).toEqual(["config-out"]);
    }
  });

  it("gives the container its config slots as bubbles", () => {
    const kinds = portKinds("LLM");
    expect(kinds).toEqual(["in", "out", "error-out", "config-in", "config-in", "config-in"]);
  });

  it("keeps the log nodes in the data flow despite their category", () => {
    for (const id of ["TraceLog", "ErrorLog"]) {
      const meta = getComponentMeta(id);
      expect(meta.category).toBe("Observability");
      expect(isAuxOnly(meta), `${id} is a transform, not aux`).toBe(false);
      expect(hasDataIn(meta)).toBe(true);
      expect(hasDataOut(meta)).toBe(true);
      expect(hasErrorOut(meta)).toBe(true);
    }
  });
});

describe("bubbles and wire ends share one position", () => {
  it("starts and ends every edge on the centre of the bubble it belongs to", () => {
    for (const component of XFLOWS_CATALOG) {
      const node = nodeOf(component.id, 321, 87);
      const meta = getComponentMeta(component.id);
      for (const port of portsForNode(node, meta)) {
        const at = { x: port.x, y: port.y };
        if (port.port === "out") {
          expect(sourcePortPos(node, "data", meta), `${component.id} data out`).toEqual(at);
        } else if (port.port === "error-out") {
          expect(sourcePortPos(node, "error", meta), `${component.id} error out`).toEqual(at);
        } else if (port.port === "config-out") {
          expect(sourcePortPos(node, "config", meta), `${component.id} config out`).toEqual(at);
        } else if (port.port === "in") {
          expect(targetPortPos(node, "data", undefined, meta)).toEqual(at);
          expect(
            targetPortPos(node, "error", undefined, meta),
            `${component.id} takes error edges on its data input`
          ).toEqual(at);
        } else if (port.port === "config-in") {
          expect(targetPortPos(node, "config", port.slot, meta)).toEqual(at);
        }
      }
    }
  });

  it("puts the two output bubbles on the node's right edge, error below data", () => {
    const node = nodeOf("LLM", 10, 20);
    const data = sourcePortPos(node, "data");
    const error = sourcePortPos(node, "error");
    expect(data).toEqual({ x: 10 + CONT_W, y: 20 + CONT_H / 2 });
    expect(error).toEqual({ x: data.x, y: data.y + ERROR_PORT_DROP });
  });

  it("aligns a node's data input with the data output it is wired from", () => {
    const source = nodeOf("PromptTemplate", 0, 0);
    const target = nodeOf("ErrorLog", 400, 0);
    expect(sourcePortPos(source, "data").y).toBe(targetPortPos(target, "data").y);
  });

  it("keeps both output bubbles inside the node's own height", () => {
    const radius = 5;
    for (const component of XFLOWS_CATALOG.filter(hasErrorOut)) {
      const node = nodeOf(component.id, 0, 0);
      const { h } = sizeFor(component);
      const error = sourcePortPos(node, "error");
      expect(
        error.y + radius,
        `${component.id}'s error bubble hangs off the bottom of the node`
      ).toBeLessThanOrEqual(h);
    }
    expect(NODE_H / 2 + ERROR_PORT_DROP + radius).toBeLessThanOrEqual(NODE_H);
  });

  it("keeps the two output bubbles far enough apart to grab separately", () => {
    expect(ERROR_PORT_DROP).toBeGreaterThan(10);
  });

  it("sizes a container larger than a plain node", () => {
    expect(sizeFor(getComponentMeta("LLM"))).toEqual({ w: CONT_W, h: CONT_H });
    expect(sizeFor(getComponentMeta("PromptTemplate"))).toEqual({ w: NODE_W, h: NODE_H });
  });
});

describe("error edges follow the port model", () => {
  const nodes = [
    { id: "in", componentId: "Input" },
    { id: "trigger", componentId: "XWSEventTrigger" },
    { id: "llm", componentId: "LLM" },
    { id: "log", componentId: "ErrorLog" },
    { id: "trace", componentId: "TraceLog" },
    { id: "langfuse", componentId: "LangfuseTracer" },
    { id: "out", componentId: "Output" },
  ];
  const check = (source, target, kind = "error", edges = []) =>
    checkConnection({ nodes, edges, source, target, kind });

  it("accepts an error edge from a node into ErrorLog", () => {
    expect(check("llm", "log")).toEqual({ ok: true });
  });

  it("accepts an error edge from a trigger", () => {
    expect(check("trigger", "log")).toEqual({ ok: true });
    expect(check("in", "log")).toEqual({ ok: true });
  });

  it("accepts ErrorLog continuing on a data edge", () => {
    expect(check("log", "out", "data")).toEqual({ ok: true });
  });

  it("accepts an error edge out of the terminal Output, which can still fail", () => {
    expect(check("out", "log")).toEqual({ ok: true });
  });

  it("still refuses a data edge out of the terminal Output", () => {
    const result = check("out", "log", "data");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/terminal/);
  });

  it("still refuses an error edge into a trigger", () => {
    const result = check("llm", "trigger");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/entry point/);
  });

  it("accepts a data edge into TraceLog, which the category rule used to refuse", () => {
    expect(check("llm", "trace", "data")).toEqual({ ok: true });
  });

  it("still refuses wiring a true aux node into the data flow", () => {
    const result = check("langfuse", "out", "data");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/config slot/);
  });

  it("refuses an error edge out of an aux node too", () => {
    const result = check("langfuse", "log");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/config slot/);
  });
});
