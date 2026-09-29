/**
 * Run arithmetic and formatting for the projects list.
 *
 * The POC counted `runs - succeeded` as failures, which only holds when
 * nothing is in flight. A production run sits in `queued`, `running` or
 * `awaiting_review` for as long as the work takes, and `cancelled`,
 * `rejected` and `escalated` are terminal without being a failure of the
 * workflow. So the success rate here is taken over runs that finished one way
 * or the other, and everything else stays out of the denominator — otherwise
 * starting a run visibly drops a project's success rate.
 *
 * Statuses mirror RunRecord.status in apps/api/app/models.py; runStatuses.test.js
 * pins the two together.
 */

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export const SUCCESS_STATUSES = ["succeeded"];
export const FAILURE_STATUSES = ["failed"];
/** Terminal, but neither a success nor a failure of the workflow itself. */
export const CLOSED_STATUSES = ["cancelled", "rejected", "escalated"];
export const IN_FLIGHT_STATUSES = ["queued", "running", "awaiting_review"];

const SUCCESS = new Set(SUCCESS_STATUSES);
const FAILURE = new Set(FAILURE_STATUSES);
const IN_FLIGHT = new Set(IN_FLIGHT_STATUSES);

function timestamp(value) {
  if (!value) return null;
  const parsed = typeof value === "number" ? value : Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Counts, success rate and last-started time for one project's runs. */
export function summariseRuns(runs, project) {
  const items = Array.isArray(runs) ? runs : [];
  let succeeded = 0;
  let failed = 0;
  let inFlight = 0;
  let lastRunAt = timestamp(project?.lastRun?.startedAt);

  for (const run of items) {
    if (SUCCESS.has(run?.status)) succeeded += 1;
    else if (FAILURE.has(run?.status)) failed += 1;
    else if (IN_FLIGHT.has(run?.status)) inFlight += 1;

    const startedAt = timestamp(run?.startedAt);
    if (startedAt !== null && (lastRunAt === null || startedAt > lastRunAt)) {
      lastRunAt = startedAt;
    }
  }

  const decided = succeeded + failed;
  return {
    total: items.length,
    succeeded,
    failed,
    inFlight,
    decided,
    rate: decided ? succeeded / decided : null,
    lastRunAt,
  };
}

/** The four numbers across the top of the page. */
export function aggregateTotals(entries) {
  let runs = 0;
  let succeeded = 0;
  let failed = 0;
  let active = 0;

  for (const entry of entries) {
    if (entry.active) active += 1;
    runs += entry.summary.total;
    succeeded += entry.summary.succeeded;
    failed += entry.summary.failed;
  }

  const decided = succeeded + failed;
  return {
    projects: entries.length,
    active,
    runs,
    rate: decided ? succeeded / decided : null,
  };
}

export function relativeTime(value, now = Date.now()) {
  const at = timestamp(value);
  if (at === null) return "never";
  const elapsed = now - at;
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.round(elapsed / MINUTE)}m ago`;
  if (elapsed < DAY) return `${Math.round(elapsed / HOUR)}h ago`;
  return `${Math.round(elapsed / DAY)}d ago`;
}

export function formatCount(value) {
  return Number(value || 0).toLocaleString("en-US");
}

export function formatRate(rate) {
  return rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

/** Green above 95%, amber above 85%, red below — matches the design's bar. */
export function rateColor(rate) {
  if (rate == null) return "#d4d4d4";
  if (rate > 0.95) return "#10b981";
  if (rate > 0.85) return "#f59e0b";
  return "#dc2626";
}

/** TriggerRecord.type is time | webhook | event; the chips read in product words. */
const TRIGGER_LABELS = { time: "Schedule", webhook: "Webhook", event: "Event" };

export function triggerLabel(trigger) {
  const type = typeof trigger === "string" ? trigger : trigger?.type;
  return TRIGGER_LABELS[type] || type || "Trigger";
}

export function triggerLabels(triggers) {
  const labels = [];
  for (const trigger of Array.isArray(triggers) ? triggers : []) {
    if (trigger?.enabled === false) continue;
    const label = triggerLabel(trigger);
    if (!labels.includes(label)) labels.push(label);
  }
  return labels;
}

/**
 * ProjectRecord has no active flag, so it lives in `metadata` — which PATCH
 * replaces wholesale, hence `metadataWithActive` merging rather than setting.
 */
export function isProjectActive(project) {
  return project?.metadata?.active !== false;
}

export function metadataWithActive(project, active) {
  return { ...(project?.metadata || {}), active };
}

export function matchesProjectQuery(project, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  if (String(project?.name || "").toLowerCase().includes(needle)) return true;
  return String(project?.id || "").toLowerCase().startsWith(needle);
}

export function filterProjects(projects, { query = "", filter = "all" } = {}) {
  return (projects || []).filter((project) => {
    if (filter === "active" && !isProjectActive(project)) return false;
    if (filter === "paused" && isProjectActive(project)) return false;
    return matchesProjectQuery(project, query);
  });
}
