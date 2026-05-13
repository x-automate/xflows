const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function parseResponse(response) {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function createWorkflow(payload) {
  const response = await fetch(`${API_BASE_URL}/workflows`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (response.status === 409) {
    return null;
  }
  return parseResponse(response);
}

export async function createProject(payload) {
  const response = await fetch(`${API_BASE_URL}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function listProjects() {
  const response = await fetch(`${API_BASE_URL}/projects`);
  return parseResponse(response);
}

export async function getProject(projectId) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}`);
  return parseResponse(response);
}

export async function updateProject(projectId, payload) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function startRun(workflowId, input) {
  const response = await fetch(`${API_BASE_URL}/workflows/${workflowId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
  return parseResponse(response);
}

export async function startProjectRun(projectId, payload) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function listProjectRuns(projectId) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/runs`);
  return parseResponse(response);
}

export async function getRun(runId) {
  const response = await fetch(`${API_BASE_URL}/runs/${runId}`);
  return parseResponse(response);
}

export async function getRunEventHistory(runId, afterId) {
  const params = new URLSearchParams();
  if (Number.isInteger(afterId)) {
    params.set("after_id", String(afterId));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE_URL}/runs/${runId}/events/history${suffix}`);
  return parseResponse(response);
}

export async function listProjectTriggers(projectId) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/triggers`);
  return parseResponse(response);
}

export async function createProjectTrigger(projectId, payload) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/triggers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function updateProjectTrigger(projectId, triggerId, payload) {
  const response = await fetch(`${API_BASE_URL}/projects/${projectId}/triggers/${triggerId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export function streamRunEvents(runId, onEvent) {
  const source = new EventSource(`${API_BASE_URL}/runs/${runId}/events`);
  const handleEvent = (event) => {
    try {
      onEvent(JSON.parse(event.data));
    } catch {
      // Ignore malformed events and keep stream alive.
    }
  };
  source.onmessage = handleEvent;
  [
    "run_started",
    "node_started",
    "node_succeeded",
    "node_failed",
    "run_succeeded",
    "run_failed",
  ].forEach((eventType) => source.addEventListener(eventType, handleEvent));
  source.onerror = () => {
    source.close();
  };
  return () => source.close();
}
