import { describe, expect, it } from "vitest";
import { getUnsupportedComponents } from "./execution-map";

const node = (componentId) => ({ id: `n_${componentId}`, componentId, params: {} });

describe("getUnsupportedComponents", () => {
  it("accepts working catalog components", () => {
    const nodes = [node("Input"), node("LLM"), node("OpenAIChat"), node("Output")];
    expect(getUnsupportedComponents(nodes)).toEqual([]);
  });

  it("flags unknown component ids", () => {
    const nodes = [node("Input"), node("Mystery")];
    expect(getUnsupportedComponents(nodes)).toEqual(["Mystery"]);
  });

  it("flags planned components even though they have a backendActivity", () => {
    const nodes = [node("Input"), node("ReActAgent"), node("Webhook")];
    const unsupported = getUnsupportedComponents(nodes);
    expect(unsupported).toContain("ReActAgent");
    expect(unsupported).toContain("Webhook");
    expect(unsupported).not.toContain("Input");
  });

  it("flags partial components only via status chips, not as unsupported", () => {
    const nodes = [node("HttpRequest"), node("LangfuseTracer")];
    expect(getUnsupportedComponents(nodes)).toEqual([]);
  });
});
