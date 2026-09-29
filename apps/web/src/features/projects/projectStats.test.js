import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CLOSED_STATUSES,
  FAILURE_STATUSES,
  IN_FLIGHT_STATUSES,
  SUCCESS_STATUSES,
  aggregateTotals,
  filterProjects,
  formatRate,
  isProjectActive,
  matchesProjectQuery,
  metadataWithActive,
  rateColor,
  relativeTime,
  summariseRuns,
  triggerLabels,
} from "./projectStats.js";

const MODELS_PATH = fileURLToPath(new URL("../../../../api/app/models.py", import.meta.url));

/** RunRecord.status in apps/api/app/models.py, read rather than remembered. */
function apiRunStatuses() {
  const source = readFileSync(MODELS_PATH, "utf8");
  const block = source.match(/class RunRecord\(BaseModel\):[\s\S]*?status: Literal\[([\s\S]*?)\]/);
  if (!block) throw new Error("Could not find RunRecord.status Literal in models.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
}

const project = (overrides = {}) => ({ id: "p1", name: "Support", ...overrides });
const run = (status, startedAt = null) => ({ status, startedAt });

describe("run status buckets", () => {
  it("accounts for every status the API can return", () => {
    const covered = [
      ...SUCCESS_STATUSES,
      ...FAILURE_STATUSES,
      ...CLOSED_STATUSES,
      ...IN_FLIGHT_STATUSES,
    ];
    expect(covered.slice().sort()).toEqual(apiRunStatuses().slice().sort());
  });
});

describe("summariseRuns", () => {
  it("counts successes and failures separately from runs still in flight", () => {
    const summary = summariseRuns([
      run("succeeded"),
      run("succeeded"),
      run("failed"),
      run("running"),
      run("awaiting_review"),
    ]);
    expect(summary.total).toBe(5);
    expect(summary.succeeded).toBe(2);
    expect(summary.failed).toBe(1);
    expect(summary.inFlight).toBe(2);
  });

  /** The POC's `runs - succeeded` made every in-flight run look like a failure. */
  it("does not let starting a run drop the success rate", () => {
    const settled = summariseRuns([run("succeeded"), run("succeeded")]);
    const withOneRunning = summariseRuns([run("succeeded"), run("succeeded"), run("running")]);
    expect(settled.rate).toBe(1);
    expect(withOneRunning.rate).toBe(1);
  });

  it("keeps cancelled, rejected and escalated out of the rate", () => {
    const summary = summariseRuns([
      run("succeeded"),
      run("cancelled"),
      run("rejected"),
      run("escalated"),
    ]);
    expect(summary.decided).toBe(1);
    expect(summary.rate).toBe(1);
  });

  it("has no rate at all until something finishes", () => {
    expect(summariseRuns([]).rate).toBeNull();
    expect(summariseRuns([run("queued")]).rate).toBeNull();
  });

  it("takes the latest start time across runs", () => {
    const summary = summariseRuns([
      run("succeeded", "2026-01-01T10:00:00Z"),
      run("failed", "2026-01-03T10:00:00Z"),
      run("succeeded", "2026-01-02T10:00:00Z"),
    ]);
    expect(summary.lastRunAt).toBe(Date.parse("2026-01-03T10:00:00Z"));
  });

  it("falls back to the project's lastRun when the run list is unavailable", () => {
    const summary = summariseRuns(null, { lastRun: { startedAt: "2026-01-04T10:00:00Z" } });
    expect(summary.total).toBe(0);
    expect(summary.lastRunAt).toBe(Date.parse("2026-01-04T10:00:00Z"));
  });
});

describe("aggregateTotals", () => {
  it("adds up runs and rates the whole estate, not the average of averages", () => {
    const totals = aggregateTotals([
      { active: true, summary: summariseRuns([run("succeeded"), run("failed")]) },
      { active: false, summary: summariseRuns(Array.from({ length: 8 }, () => run("succeeded"))) },
    ]);
    expect(totals.projects).toBe(2);
    expect(totals.active).toBe(1);
    expect(totals.runs).toBe(10);
    expect(totals.rate).toBeCloseTo(9 / 10);
  });

  it("reports no rate when nothing has finished anywhere", () => {
    expect(aggregateTotals([{ active: true, summary: summariseRuns([]) }]).rate).toBeNull();
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-01-10T12:00:00Z");

  it("reads in the largest unit that fits", () => {
    expect(relativeTime(null, now)).toBe("never");
    expect(relativeTime("2026-01-10T11:59:30Z", now)).toBe("just now");
    expect(relativeTime("2026-01-10T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-01-10T06:00:00Z", now)).toBe("6h ago");
    expect(relativeTime("2026-01-07T12:00:00Z", now)).toBe("3d ago");
  });

  it("treats an unparseable timestamp as no run rather than as NaN", () => {
    expect(relativeTime("not a date", now)).toBe("never");
  });
});

describe("formatting", () => {
  it("shows an em dash rather than 0% when there is no rate", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(0)).toBe("0.0%");
    expect(formatRate(0.9876)).toBe("98.8%");
  });

  it("colours the bar green, amber, red by the design's thresholds", () => {
    expect(rateColor(0.99)).toBe("#10b981");
    expect(rateColor(0.9)).toBe("#f59e0b");
    expect(rateColor(0.5)).toBe("#dc2626");
  });
});

describe("trigger chips", () => {
  it("names TriggerRecord types in product words", () => {
    expect(triggerLabels([{ type: "time" }, { type: "webhook" }, { type: "event" }])).toEqual([
      "Schedule",
      "Webhook",
      "Event",
    ]);
  });

  it("drops disabled triggers and collapses duplicates", () => {
    expect(
      triggerLabels([
        { type: "time" },
        { type: "time" },
        { type: "webhook", enabled: false },
      ])
    ).toEqual(["Schedule"]);
  });
});

describe("active flag", () => {
  /** ProjectRecord has no active column, so it rides in metadata. */
  it("treats a project with no metadata as active", () => {
    expect(isProjectActive(project())).toBe(true);
    expect(isProjectActive(project({ metadata: {} }))).toBe(true);
    expect(isProjectActive(project({ metadata: { active: false } }))).toBe(false);
  });

  /** PATCH replaces metadata wholesale, so the rest of it has to be carried. */
  it("keeps the rest of metadata when toggling", () => {
    const existing = project({ metadata: { active: true, owner: "ops" } });
    expect(metadataWithActive(existing, false)).toEqual({ active: false, owner: "ops" });
  });
});

describe("search and filter", () => {
  const projects = [
    project({ id: "0716730a-0a53-4c7c", name: "Customer Support Agent" }),
    project({ id: "5b2e91c4-7f3a-4d8e", name: "Invoice Extractor", metadata: { active: false } }),
  ];

  it("matches a name case-insensitively and a UUID by prefix", () => {
    expect(matchesProjectQuery(projects[0], "support")).toBe(true);
    expect(matchesProjectQuery(projects[0], "0716")).toBe(true);
    expect(matchesProjectQuery(projects[0], "0a53")).toBe(false);
    expect(matchesProjectQuery(projects[0], "")).toBe(true);
  });

  it("combines the segmented filter with the search box", () => {
    expect(filterProjects(projects, { filter: "active" }).map((item) => item.name)).toEqual([
      "Customer Support Agent",
    ]);
    expect(filterProjects(projects, { filter: "paused" }).map((item) => item.name)).toEqual([
      "Invoice Extractor",
    ]);
    expect(filterProjects(projects, { filter: "active", query: "invoice" })).toEqual([]);
  });
});
