import { describe, expect, it } from "vitest";
import { checkConnection } from "./connection-rules.js";

const NODES = [
  { id: "in", componentId: "Input" },
  { id: "prompt", componentId: "PromptTemplate" },
  { id: "llm", componentId: "LLM" },
  { id: "provider", componentId: "LiteLLM", parent: "llm" },
  { id: "out", componentId: "Output" },
  { id: "trace", componentId: "LangfuseTracer" },
  { id: "store", componentId: "VectorStore" },
  { id: "http", componentId: "HttpRequest" },
];

const check = (source, target, kind = "data", slot, edges = []) =>
  checkConnection({ nodes: NODES, edges, source, target, kind, slot });

describe("data edges", () => {
  it("accepts a normal forward connection", () => {
    expect(check("prompt", "llm")).toEqual({ ok: true });
  });

  it("rejects an edge into an Input", () => {
    const result = check("prompt", "in");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/entry point/);
  });

  it("rejects an edge out of an Output", () => {
    const result = check("out", "prompt");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/terminal/);
  });

  it("rejects a self connection", () => {
    expect(check("llm", "llm").ok).toBe(false);
  });

  it("rejects a duplicate of an existing edge", () => {
    const edges = [{ id: "e1", source: "in", target: "prompt", kind: "data" }];
    const result = check("in", "prompt", "data", undefined, edges);
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/already connected/);
  });

  it("allows the same pair with a different edge kind", () => {
    const edges = [{ id: "e1", source: "llm", target: "out", kind: "data" }];
    expect(check("llm", "out", "error", undefined, edges)).toEqual({ ok: true });
  });

  it("rejects an edge that would close a cycle", () => {
    const edges = [
      { id: "e1", source: "prompt", target: "llm", kind: "data" },
      { id: "e2", source: "llm", target: "http", kind: "data" },
    ];
    const result = check("http", "prompt", "data", undefined, edges);
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/loop/);
  });

  it("rejects wiring an Observability node into the data flow", () => {
    const result = check("trace", "out");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/config slot/);
  });

  it("rejects wiring a nested provider directly", () => {
    const result = check("provider", "out");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/through their container/);
  });
});

describe("config edges", () => {
  it("accepts an Observability node in the tracer slot", () => {
    expect(check("trace", "llm", "config", "tracer")).toEqual({ ok: true });
  });

  it("accepts a Memory node in the memory slot", () => {
    expect(check("store", "llm", "config", "memory")).toEqual({ ok: true });
  });

  it("rejects a Memory node in the tracer slot", () => {
    const result = check("store", "llm", "config", "tracer");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/accepts Observability/);
  });

  it("rejects a slot the target does not have", () => {
    const result = check("trace", "prompt", "config", "tracer");
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/no "tracer" slot/);
  });

  it("does not treat a config edge as a cycle", () => {
    const edges = [{ id: "e1", source: "llm", target: "store", kind: "data" }];
    expect(check("store", "llm", "config", "memory", edges)).toEqual({ ok: true });
  });
});
