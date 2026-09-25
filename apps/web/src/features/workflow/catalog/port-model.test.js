import { describe, expect, it } from "vitest";
import { XFLOWS_CATALOG, canSourceConfigEdge, getComponentMeta } from "./catalog-meta.js";
import { checkConnection, isAuxOnly } from "./connection-rules.js";

/**
 * The port model the canvas renders, asserted against the catalog.
 *
 * Canvas.jsx gates ports on `kind`, never on category — `TraceLog` and
 * `ErrorLog` are categorised Observability but are ordinary inline transforms
 * with real data ports, and gating on the category stripped them.
 */
const hasDataIn = (meta) => !isAuxOnly(meta) && meta.kind !== "input";
const hasDataOut = (meta) => !isAuxOnly(meta) && meta.kind !== "output";
const hasErrorOut = hasDataOut;

describe("every node offers both output bubbles", () => {
  it("pairs a data output with an error output on every executing node", () => {
    for (const component of XFLOWS_CATALOG) {
      expect(
        hasErrorOut(component),
        `${component.id} has a data output but no error output`
      ).toBe(hasDataOut(component));
    }
  });

  it("gives the terminal Output node no outputs at all", () => {
    const output = getComponentMeta("Output");
    expect(hasDataIn(output)).toBe(true);
    expect(hasDataOut(output)).toBe(false);
    expect(hasErrorOut(output)).toBe(false);
  });

  it("gives triggers an error output but no data input", () => {
    for (const id of ["Input", "Webhook", "XWSEventTrigger"]) {
      const meta = getComponentMeta(id);
      expect(meta.kind, `${id} should be an input kind`).toBe("input");
      expect(hasDataIn(meta), `${id} should take no data input`).toBe(false);
      expect(hasDataOut(meta)).toBe(true);
      expect(hasErrorOut(meta), `${id} should be able to route its failures`).toBe(true);
    }
  });

  it("gives aux nodes a config port instead of data ports", () => {
    for (const component of XFLOWS_CATALOG.filter((item) => item.kind === "aux")) {
      expect(hasDataIn(component), `${component.id} should have no data input`).toBe(false);
      expect(hasDataOut(component), `${component.id} should have no data output`).toBe(false);
      expect(
        canSourceConfigEdge(component),
        `${component.id} is aux so it must be able to source a config edge`
      ).toBe(true);
    }
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

  it("still refuses an error edge out of the terminal Output", () => {
    const result = check("out", "log");
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
});
