const PROJECTS_KEY = "xflows_projects";

function readProjects() {
  try {
    return JSON.parse(localStorage.getItem(PROJECTS_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeProjects(projects) {
  localStorage.setItem(PROJECTS_KEY, JSON.stringify(projects));
}

function defaultTrigger() {
  return {
    id: `trg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    type: "time",
    enabled: true,
    queue: "support_tickets",
    time: "08:00",
    timezone: "local",
  };
}

export function createProject(name, preferredId) {
  const id =
    preferredId ||
    (typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `p_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`);
  const now = new Date().toISOString();
  const projects = readProjects();
  const project = {
    id,
    name: name.trim() || "Untitled Project",
    createdAt: now,
    updatedAt: now,
    graph: null,
    configs: {},
    triggers: [defaultTrigger()],
    trigger: defaultTrigger(),
    lastRun: null,
    runs: [],
  };
  projects[id] = project;
  writeProjects(projects);
  return project;
}

export function upsertProject(project) {
  const projects = readProjects();
  const existing = projects[project.id];
  const merged = {
    ...(existing || {}),
    ...project,
    updatedAt: new Date().toISOString(),
    graph: project.graph ?? existing?.graph ?? null,
    configs: project.configs ?? existing?.configs ?? {},
    triggers: project.triggers ?? existing?.triggers ?? [defaultTrigger()],
    trigger: project.trigger ?? existing?.trigger ?? defaultTrigger(),
    lastRun: project.lastRun ?? existing?.lastRun ?? null,
    runs: project.runs ?? existing?.runs ?? [],
  };
  projects[project.id] = merged;
  writeProjects(projects);
  return merged;
}

export function listProjects() {
  return Object.values(readProjects()).sort((a, b) =>
    String(b.updatedAt).localeCompare(String(a.updatedAt))
  );
}

export function getProject(projectId) {
  return readProjects()[projectId] || null;
}

export function updateProject(projectId, updates) {
  const projects = readProjects();
  const existing = projects[projectId];
  if (!existing) return null;
  const project = {
    ...existing,
    ...updates,
    updatedAt: new Date().toISOString(),
  };
  projects[projectId] = project;
  writeProjects(projects);
  return project;
}

export function updateProjectGraph(projectId, graph) {
  return updateProject(projectId, { graph });
}

export function getProjectRuns(projectId) {
  const project = getProject(projectId);
  return [...(project?.runs || [])].sort((a, b) =>
    String(b.startedAt || "").localeCompare(String(a.startedAt || ""))
  );
}

export function addProjectRun(projectId, run) {
  const project = getProject(projectId);
  if (!project) return null;
  const nextRuns = [run, ...(project.runs || []).filter((item) => item.id !== run.id)];
  return updateProject(projectId, {
    runs: nextRuns,
    lastRun: {
      input: run.input,
      status: run.status,
      startedAt: run.startedAt || new Date().toISOString(),
      runId: run.id,
    },
  });
}

export function updateProjectRun(projectId, runId, updates) {
  const project = getProject(projectId);
  if (!project) return null;
  const runs = (project.runs || []).map((run) =>
    run.id === runId ? { ...run, ...updates } : run
  );
  const active = runs.find((run) => run.id === runId);
  return updateProject(projectId, {
    runs,
    lastRun: active
      ? {
          input: active.input,
          status: active.status,
          startedAt: active.startedAt || new Date().toISOString(),
          runId: active.id,
        }
      : project.lastRun,
  });
}

export function getProjectTriggers(projectId) {
  const project = getProject(projectId);
  if (!project) return [];
  if (Array.isArray(project.triggers) && project.triggers.length) {
    return project.triggers;
  }
  if (project.trigger) {
    return [{ ...project.trigger, id: project.trigger.id || `trg_${project.id}` }];
  }
  return [];
}

export function saveProjectTriggers(projectId, triggers) {
  const nextTriggers = triggers.map((trigger, idx) => ({
    ...trigger,
    id: trigger.id || `trg_${Date.now()}_${idx}`,
  }));
  return updateProject(projectId, {
    triggers: nextTriggers,
    trigger: nextTriggers[0] || null,
  });
}
