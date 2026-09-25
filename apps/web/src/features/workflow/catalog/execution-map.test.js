import { describe, expect, it } from "vitest";
import { getUnsupportedComponents } from "./execution-map";

const node = (componentId) => ({ id: `n_${componentId}`, componentId, params: {} });

describe("getUnsupportedComponents", () => {
  it("accepts working catalog components", () => {
    const nodes = [node("Input"), node("LLM"), node("OpenAIChat"), node("Output")];
    expect(getUnsupportedComponents(nodes)).toEqual([]);
  });

  it("accepts the trigger, audit and log nodes now that they execute", () => {
    const nodes = [node("Webhook"), node("XWSEventTrigger"), node("XWSAudit"), node("TraceLog")];
    expect(getUnsupportedComponents(nodes)).toEqual([]);
  });

  it("flags unknown component ids", () => {
    const nodes = [node("Input"), node("Mystery")];
    expect(getUnsupportedComponents(nodes)).toEqual(["Mystery"]);
  });

  it("flags planned components even though they have a backendActivity", () => {
    const nodes = [node("Input"), node("ReActAgent"), node("CodeExec")];
    const unsupported = getUnsupportedComponents(nodes);
    expect(unsupported).toContain("ReActAgent");
    expect(unsupported).toContain("CodeExec");
    expect(unsupported).not.toContain("Input");
  });

  it("flags partial components only via status chips, not as unsupported", () => {
    const nodes = [node("HttpRequest"), node("LangfuseTracer")];
    expect(getUnsupportedComponents(nodes)).toEqual([]);
  });
});
