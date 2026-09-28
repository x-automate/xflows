import { describe, expect, it } from "vitest";
import { connectCandidates, filterCandidates, linkFor } from "./connect-candidates.js";

/**
 * What the connect menu is allowed to offer.
 *
 * Every row has to survive the same `checkConnection` gate the canvas uses,
 * or the menu would offer a connection and then refuse to make it.
 */
const NODES = [
  { id: "in", componentId: "Input", x: 0, y: 0 },
  { id: "prompt", componentId: "PromptTemplate", x: 200, y: 0 },
  { id: "llm", componentId: "LLM", x: 400, y: 0 },
  { id: "prov", componentId: "OpenAIChat", parent: "llm" },
  { id: "out", componentId: "Output", x: 700, y: 0 },
  { id: "log", componentId: "ErrorLog", x: 700, y: 200 },
  { id: "tracer", componentId: "LangfuseTracer", x: 400, y: 300 },
];

const ids = (rows) => rows.map((row) => row.id);
const componentIds = (rows) => rows.map((row) => row.componentId);
const candidates = (pending, edges = []) =>
  connectCandidates({ nodes: NODES, edges, pending });

describe("linkFor", () => {
  it("puts the anchor on the source end of a forward wire", () => {
    expect(linkFor({ anchorId: "a", direction: "forward", kind: "data" }, "b")).toEqual({
      source: "a",
      target: "b",
      kind: "data",
      slot: undefined,
    });
  });

  it("puts the anchor on the target end of a reverse wire", () => {
    expect(linkFor({ anchorId: "a", direction: "reverse", kind: "data" }, "b")).toEqual({
      source: "b",
      target: "a",
      kind: "data",
      slot: undefined,
    });
  });
});

describe("a data wire pulled from an output", () => {
  const pending = { anchorId: "prompt", direction: "forward", kind: "data" };

  it("offers the nodes that can take a data input", () => {
    expect(ids(candidates(pending).onCanvas).sort()).toEqual(["llm", "log", "out"]);
  });

  it("leaves out the trigger, the aux node, the nested provider and itself", () => {
    const rows = ids(candidates(pending).onCanvas);
    expect(rows).not.toContain("in");
    expect(rows).not.toContain("tracer");
    expect(rows).not.toContain("prov");
    expect(rows).not.toContain("prompt");
  });

  it("offers components it could drop in, minus the ones that cannot take data", () => {
    const rows = componentIds(candidates(pending).create);
    expect(rows).toContain("ErrorLog");
    expect(rows).toContain("Output");
    expect(rows).not.toContain("Input");
    expect(rows).not.toContain("Webhook");
    expect(rows).not.toContain("LangfuseTracer");
    expect(rows).not.toContain("OpenAIChat");
    expect(rows).not.toContain("CodeExec");
  });

  it("drops a node that is already connected the same way", () => {
    const edges = [{ id: "e1", source: "prompt", target: "llm", kind: "data" }];
    expect(ids(candidates(pending, edges).onCanvas)).not.toContain("llm");
  });

  it("drops a node that would close a loop", () => {
    const edges = [{ id: "e1", source: "llm", target: "prompt", kind: "data" }];
    expect(ids(candidates(pending, edges).onCanvas)).not.toContain("llm");
  });
});

describe("a data wire pulled backwards from an input", () => {
  const pending = { anchorId: "llm", direction: "reverse", kind: "data" };

  it("offers the nodes that have a data output", () => {
    expect(ids(candidates(pending).onCanvas).sort()).toEqual(["in", "log", "prompt"]);
  });

  it("leaves out the terminal Output, which produces no data", () => {
    expect(ids(candidates(pending).onCanvas)).not.toContain("out");
  });

  it("offers triggers as components to create, since they feed a graph", () => {
    const rows = componentIds(candidates(pending).create);
    expect(rows).toContain("Input");
    expect(rows).toContain("Webhook");
    expect(rows).not.toContain("Output");
  });
});

describe("an error wire", () => {
  const pending = { anchorId: "llm", direction: "forward", kind: "error" };

  it("offers the same targets a data wire would", () => {
    expect(ids(candidates(pending).onCanvas).sort()).toEqual(["log", "out", "prompt"]);
    const asData = { ...pending, kind: "data" };
    expect(ids(candidates(pending).onCanvas).sort()).toEqual(
      ids(candidates(asData).onCanvas).sort()
    );
  });

  it("can be pulled backwards out of the terminal Output", () => {
    const rows = candidates({ anchorId: "log", direction: "reverse", kind: "error" }).onCanvas;
    expect(ids(rows)).toContain("out");
  });
});

describe("a config wire", () => {
  it("offers one row per slot that accepts the source", () => {
    const rows = candidates({ anchorId: "tracer", direction: "forward", kind: "config" }).onCanvas;
    expect(rows.map((row) => [row.id, row.slot])).toEqual([["llm", "tracer"]]);
  });

  it("offers only what a named slot accepts when pulled from the slot", () => {
    const pending = {
      anchorId: "llm",
      direction: "reverse",
      kind: "config",
      slot: "memory",
    };
    expect(componentIds(candidates(pending).create)).toEqual(["VectorStore"]);
    expect(ids(candidates(pending).onCanvas)).toEqual([]);
  });

  it("offers the tracer already on the canvas for the tracer slot", () => {
    const pending = {
      anchorId: "llm",
      direction: "reverse",
      kind: "config",
      slot: "tracer",
    };
    expect(ids(candidates(pending).onCanvas)).toContain("tracer");
  });
});

describe("filterCandidates", () => {
  const rows = [
    { name: "Error Log", componentId: "ErrorLog", category: "Observability", desc: "logs" },
    { name: "Output", componentId: "Output", category: "I/O", desc: "final answer" },
  ];

  it("matches on name, id, category or description, case-insensitively", () => {
    expect(filterCandidates(rows, "error")).toHaveLength(1);
    expect(filterCandidates(rows, "i/o")).toHaveLength(1);
    expect(filterCandidates(rows, "final")).toHaveLength(1);
    expect(filterCandidates(rows, "")).toHaveLength(2);
    expect(filterCandidates(rows, "zzz")).toHaveLength(0);
  });
});

describe("a wire with no anchor", () => {
  it("offers nothing rather than throwing", () => {
    expect(connectCandidates({ nodes: NODES, edges: [], pending: null })).toEqual({
      onCanvas: [],
      create: [],
    });
  });
});
