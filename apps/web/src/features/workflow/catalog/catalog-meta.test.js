import { describe, expect, it } from "vitest";
import {
  CATEGORY_COLORS,
  STATUS_META,
  XFLOWS_CATALOG,
  getComponentMeta,
  getRequiredProjectConfigs,
  isPlaceable,
} from "./catalog-meta";

describe("catalog registry", () => {
  it("contains exactly the 41 known components", () => {
    expect(XFLOWS_CATALOG).toHaveLength(41);
  });

  it("gives every component a valid status", () => {
    for (const component of XFLOWS_CATALOG) {
      expect(STATUS_META[component.status], `${component.id} has invalid status`).toBeDefined();
    }
  });

  it("keeps category colors aligned with used categories", () => {
    for (const component of XFLOWS_CATALOG) {
      expect(CATEGORY_COLORS[component.category], `${component.id} missing color`).toBeDefined();
    }
  });

  it("maps only working and partial components to backend execution", () => {
    const planned = XFLOWS_CATALOG.filter((component) => component.status === "planned");
    expect(planned.length).toBeGreaterThan(0);
    for (const component of planned) {
      expect(component.backendActivity).toBeDefined();
    }
  });
});

describe("isPlaceable", () => {
  it("allows working and partial components", () => {
    expect(isPlaceable(getComponentMeta("Input"))).toBe(true);
    expect(isPlaceable(getComponentMeta("HttpRequest"))).toBe(true);
  });

  it("allows the trigger and audit nodes now that they are wired end to end", () => {
    expect(isPlaceable(getComponentMeta("Webhook"))).toBe(true);
    expect(isPlaceable(getComponentMeta("XWSEventTrigger"))).toBe(true);
    expect(isPlaceable(getComponentMeta("XWSAudit"))).toBe(true);
    expect(isPlaceable(getComponentMeta("TraceLog"))).toBe(true);
  });

  it("rejects planned components", () => {
    expect(isPlaceable(getComponentMeta("ReActAgent"))).toBe(false);
    expect(isPlaceable(getComponentMeta("CodeExec"))).toBe(false);
  });
});

describe("getRequiredProjectConfigs", () => {
  it("collects project configs from provider and tracer nodes", () => {
    const nodes = [
      { id: "l1", componentId: "LiteLLM", params: {} },
      { id: "t1", componentId: "LangfuseTracer", params: {} },
    ];
    const required = getRequiredProjectConfigs(nodes);
    const keys = required.map((item) => item.key);
    expect(keys).toContain("litellmApiKey");
    expect(keys).toContain("langfuseSecretKey");
  });

  it("deduplicates keys across nodes", () => {
    const nodes = [
      { id: "l1", componentId: "LiteLLM", params: {} },
      { id: "l2", componentId: "LiteLLM", params: {} },
    ];
    const keys = getRequiredProjectConfigs(nodes).map((item) => item.key);
    expect(keys).toEqual([...new Set(keys)]);
  });
});
