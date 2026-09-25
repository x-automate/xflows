import { describe, expect, it } from "vitest";
import { validateWorkflow } from "./useWorkflowValidation";

const node = (id, componentId) => ({ id, componentId, params: {} });
const edge = (id, source, target, kind = "data") => ({ id, source, target, kind });

const UNREACHABLE_OUTPUT = /reachable only through error \(red dashed\) edges/;

const nodes = [
  node("i1", "Input"),
  node("p1", "PromptTemplate"),
  node("a1", "XWSAudit"),
  node("o1", "Output"),
];

describe("validateWorkflow error-edge wiring", () => {
  it("flags an Output that only a failing run would reach", () => {
    // Reproduces the canvas mis-wiring where the audit node and the Output were
    // both connected from the error port: a successful run produces nothing.
    const edges = [
      edge("e1", "i1", "p1"),
      edge("e2", "p1", "a1", "error"),
      edge("e3", "a1", "o1", "error"),
    ];
    const { errors } = validateWorkflow(nodes, edges);
    const output = errors.filter((message) => UNREACHABLE_OUTPUT.test(message));
    expect(output).toHaveLength(1);
    expect(output[0]).toContain('Output "Output"');
  });

  it("accepts the same graph once it is rewired with data edges", () => {
    const edges = [
      edge("e1", "i1", "p1"),
      edge("e2", "p1", "a1"),
      edge("e3", "a1", "o1"),
    ];
    expect(validateWorkflow(nodes, edges).errors).toEqual([]);
  });

  it("allows a deliberate error branch alongside a working data path", () => {
    // LLM-style failure logging: the audit node hangs off the error port on
    // purpose, and the Output still has its own data path.
    const edges = [
      edge("e1", "i1", "p1"),
      edge("e2", "p1", "o1"),
      edge("e3", "p1", "a1", "error"),
    ];
    expect(validateWorkflow(nodes, edges).errors).toEqual([]);
  });

  it("does not call an error-wired node unconnected", () => {
    const edges = [
      edge("e1", "i1", "p1"),
      edge("e2", "p1", "o1"),
      edge("e3", "p1", "a1", "error"),
    ];
    const { errors } = validateWorkflow(nodes, edges);
    expect(errors).not.toContain('"XWS Audit" is not connected.');
  });

  it("still reports a node with no edges at all as not connected", () => {
    const edges = [edge("e1", "i1", "o1")];
    const graph = nodes.filter((item) => item.id !== "p1");
    expect(validateWorkflow(graph, edges).errors).toContain('"XWS Audit" is not connected.');
  });
});
