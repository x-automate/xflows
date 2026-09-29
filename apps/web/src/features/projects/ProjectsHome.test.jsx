// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectsHome from "./ProjectsHome";

/**
 * The projects list reads three endpoints per page load (`/projects`, plus
 * runs and triggers for each row) and degrades to localStorage when any of
 * them is unreachable. These tests drive it through a stubbed fetch so the
 * degraded paths are exercised, not just the happy one.
 */

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container;
let root;
let requests;

const PROJECTS = [
  {
    id: "0716730a-0a53-4c7c-8c16-aa26cd51121d",
    name: "Customer Support Agent",
    description: "Replies to inbound support tickets.",
    metadata: {},
  },
  {
    id: "5b2e91c4-7f3a-4d8e-9a61-3c0d2f8b7e14",
    name: "Invoice Extractor",
    description: "Parses PDF invoices into JSON.",
    metadata: { active: false, owner: "ops" },
  },
];

const RUNS = {
  "0716730a-0a53-4c7c-8c16-aa26cd51121d": [
    { id: "r1", status: "succeeded", startedAt: "2026-01-01T10:00:00Z" },
    { id: "r2", status: "succeeded", startedAt: "2026-01-02T10:00:00Z" },
    { id: "r3", status: "failed", startedAt: "2026-01-03T10:00:00Z" },
    { id: "r4", status: "running", startedAt: "2026-01-04T10:00:00Z" },
  ],
  "5b2e91c4-7f3a-4d8e-9a61-3c0d2f8b7e14": [],
};

const TRIGGERS = {
  "0716730a-0a53-4c7c-8c16-aa26cd51121d": [{ type: "time" }, { type: "webhook" }],
  "5b2e91c4-7f3a-4d8e-9a61-3c0d2f8b7e14": [],
};

function json(body) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function stubFetch({ projects = PROJECTS, listFails = false } = {}) {
  globalThis.fetch = vi.fn((url, init = {}) => {
    const { pathname } = new URL(url);
    requests.push({ method: init.method || "GET", pathname, body: init.body });

    const runsMatch = pathname.match(/^\/projects\/([^/]+)\/runs$/);
    if (runsMatch) return json(RUNS[runsMatch[1]] ?? []);

    const triggersMatch = pathname.match(/^\/projects\/([^/]+)\/triggers$/);
    if (triggersMatch) return json(TRIGGERS[triggersMatch[1]] ?? []);

    if (pathname === "/projects") {
      if (listFails) return Promise.reject(new Error("offline"));
      return json(projects);
    }

    const projectMatch = pathname.match(/^\/projects\/([^/]+)$/);
    if (projectMatch) {
      const patch = init.body ? JSON.parse(init.body) : {};
      const existing = projects.find((item) => item.id === projectMatch[1]) || {
        id: projectMatch[1],
        name: "New",
      };
      return json({ ...existing, ...patch });
    }

    return Promise.reject(new Error(`unexpected ${pathname}`));
  });
}

async function render() {
  await act(async () => {
    root.render(
      createElement(MemoryRouter, null, createElement(ProjectsHome, null))
    );
  });
  // One tick for /projects, a second for the per-project runs and triggers.
  await act(async () => {});
}

const rows = () => [...container.querySelectorAll(".ph-row")];
const rowNames = () => rows().map((row) => row.querySelector(".ph-row-title").textContent);
const statValue = (index) =>
  container.querySelectorAll(".ph-stat")[index].querySelector(".ph-stat-value").textContent;

beforeEach(() => {
  localStorage.clear();
  requests = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  stubFetch();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("projects list", () => {
  it("shows a row per project with its name, description and id", async () => {
    await render();
    expect(rowNames()).toEqual(["Customer Support Agent", "Invoice Extractor"]);
    expect(rows()[0].querySelector(".ph-row-desc").textContent).toBe(
      "Replies to inbound support tickets."
    );
    expect(rows()[0].querySelector(".ph-row-id").textContent).toBe(PROJECTS[0].id);
  });

  it("falls back to the row's own copy when a project has no description", async () => {
    stubFetch({ projects: [{ id: "p1", name: "Bare", metadata: {} }] });
    await render();
    expect(rows()[0].querySelector(".ph-row-desc").textContent).toBe("No description");
  });

  it("counts runs and rates them over what finished, not over what started", async () => {
    await render();
    const [support] = rows();
    expect(support.querySelector(".ph-row-runs .ph-num").textContent).toBe("4");
    expect(support.querySelector(".ph-fail").textContent).toBe("1 failed");
    // 2 succeeded of 3 decided — the `running` run is not counted against it.
    expect(support.querySelector(".ph-row-rate .ph-num").textContent).toBe("66.7%");
  });

  it("shows no rate rather than 0% for a project that has never run", async () => {
    await render();
    const invoice = rows()[1];
    expect(invoice.querySelector(".ph-row-rate").textContent).toBe("—");
    expect(invoice.querySelector(".ph-row-last").textContent).toBe("never");
  });

  it("totals the whole estate across the stat tiles", async () => {
    await render();
    expect(statValue(0)).toBe("2");
    expect(statValue(1)).toBe("1");
    expect(statValue(2)).toBe("4");
    expect(statValue(3)).toBe("66.7%");
  });

  it("names trigger types in product words and says none when there are none", async () => {
    await render();
    expect(
      [...rows()[0].querySelectorAll(".ph-chip")].map((chip) => chip.textContent)
    ).toEqual(["Schedule", "Webhook"]);
    expect(rows()[1].querySelector(".ph-row-triggers").textContent).toBe("none");
  });
});

describe("search and filter", () => {
  it("narrows the list by name", async () => {
    await render();
    const search = container.querySelector(".ph-search");
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      ).set.call(search, "invoice");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(rowNames()).toEqual(["Invoice Extractor"]);
  });

  it("splits active from paused and counts each in the segmented control", async () => {
    await render();
    const [, activeButton, pausedButton] = container.querySelectorAll(".ph-seg button");
    expect(activeButton.querySelector(".ph-seg-count").textContent).toBe("1");
    expect(pausedButton.querySelector(".ph-seg-count").textContent).toBe("1");

    await act(async () => pausedButton.click());
    expect(rowNames()).toEqual(["Invoice Extractor"]);

    await act(async () => activeButton.click());
    expect(rowNames()).toEqual(["Customer Support Agent"]);
  });

  it("says so when the filters match nothing but projects exist", async () => {
    await render();
    const search = container.querySelector(".ph-search");
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      ).set.call(search, "nothing matches this");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.querySelector(".ph-empty").textContent).toContain(
      "No projects match these filters"
    );
  });
});

describe("pausing a project", () => {
  it("writes the flag into metadata without dropping the rest of it", async () => {
    await render();
    const flag = rows()[1].querySelector(".ph-flag");
    expect(flag.textContent).toBe("Paused");

    await act(async () => flag.click());

    const patch = requests.find((request) => request.method === "PATCH");
    expect(patch.pathname).toBe(`/projects/${PROJECTS[1].id}`);
    expect(JSON.parse(patch.body)).toEqual({ metadata: { active: true, owner: "ops" } });
    expect(rows()[1].querySelector(".ph-flag").textContent).toBe("Active");
  });

  it("does not refetch every project's run history just to pause one", async () => {
    await render();
    const runRequestsBefore = requests.filter((request) => request.pathname.endsWith("/runs")).length;

    await act(async () => rows()[0].querySelector(".ph-flag").click());

    const runRequestsAfter = requests.filter((request) => request.pathname.endsWith("/runs")).length;
    expect(runRequestsAfter).toBe(runRequestsBefore);
  });
});

describe("when the API is unreachable", () => {
  it("says the list came from this browser instead of rendering it as the truth", async () => {
    stubFetch({ listFails: true });
    await render();
    expect(container.querySelector(".ph-error").textContent).toContain("API is unreachable");
  });

  it("offers a first project rather than an empty page", async () => {
    stubFetch({ projects: [] });
    await render();
    expect(container.querySelector(".ph-empty").textContent).toContain("No projects yet");
  });
});

describe("new project modal", () => {
  it("opens from the header and generates the id it says it will use", async () => {
    await render();
    await act(async () => container.querySelector(".ph-btn-primary").click());

    const modal = document.querySelector(".ph-modal");
    expect(modal).not.toBeNull();
    const id = modal.querySelector(".ph-new-uuid").textContent;
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
    expect(modal.querySelector(".ph-field-help").textContent).toContain(id.slice(0, 8));
  });

  it("will not create a project without a name", async () => {
    await render();
    await act(async () => container.querySelector(".ph-btn-primary").click());
    const create = [...document.querySelectorAll(".ph-modal-foot button")].at(-1);
    expect(create.disabled).toBe(true);
  });
});
