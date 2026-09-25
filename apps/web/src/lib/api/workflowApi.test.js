import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { RUN_EVENT_TYPES } from "./workflowApi.js";

const MODELS_PATH = fileURLToPath(
  new URL("../../../../api/app/models.py", import.meta.url)
);

/**
 * The API sends every run event as a named SSE event, so a type the client
 * does not subscribe to is dropped silently — which is how node_skipped and
 * node_routed_to_error went missing from the trace. Pin the two lists together.
 */
function apiRunEventTypes() {
  const source = readFileSync(MODELS_PATH, "utf8");
  const block = source.match(/class RunEvent\(BaseModel\):[\s\S]*?type: Literal\[([\s\S]*?)\]/);
  if (!block) throw new Error("Could not find RunEvent.type Literal in models.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
}

describe("streamRunEvents subscriptions", () => {
  it("covers every run event type the API can emit", () => {
    expect([...RUN_EVENT_TYPES].sort()).toEqual([...apiRunEventTypes()].sort());
  });

  it("does not subscribe to types the API never sends", () => {
    const known = new Set(apiRunEventTypes());
    expect(RUN_EVENT_TYPES.filter((type) => !known.has(type))).toEqual([]);
  });
});
