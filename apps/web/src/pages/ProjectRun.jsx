import { useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { getRun, startProjectRun, updateProject as updateProjectApi } from "../lib/api/workflowApi";
import { addProjectRun, getProjectRuns, updateProjectRun } from "../lib/projectStore";

const DEFAULT_TICKET =
  "Customer ticket: I cannot access my account after resetting my password. Please help.";

function ProjectRun() {
  const { projectId, runId } = useParams();
  const { project } = useOutletContext();
  const navigate = useNavigate();
  const [ticket, setTicket] = useState(project.lastRun?.input || DEFAULT_TICKET);
  const [runRecord, setRunRecord] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!runId || runId === "new") {
      setRunRecord(null);
      return;
    }
    const local = getProjectRuns(projectId).find((item) => item.id === runId);
    if (local) {
      setRunRecord(local);
    }
    let active = true;
    const refresh = async () => {
      try {
        const run = await getRun(runId);
        if (!active) return;
        setRunRecord(run);
        updateProjectRun(projectId, run.id, run);
      } catch {
        // Local fallback handles pre-API runs.
      }
    };
    refresh();
    return () => {
      active = false;
    };
  }, [projectId, runId]);

  const onRun = async () => {
    const graph = project.graph;
    if (!graph?.nodes?.length) {
      setError("Add at least one node in Flow before starting a run.");
      return;
    }
    setError("");
    try {
      const run = await startProjectRun(projectId, {
        input: ticket,
        workflow: {
          name: `${project.name} Flow`,
          description: `Project workflow for ${project.name}`,
          nodes: graph.nodes,
          edges: graph.edges,
        },
      });
      addProjectRun(projectId, run);
      updateProjectApi(projectId, {
        lastRun: {
          input: run.input,
          status: run.status,
          startedAt: run.startedAt || new Date().toISOString(),
          runId: run.id,
        },
      }).catch(() => {
        // Local run history remains available if API patch fails.
      });
      navigate(`/project/${projectId}/run/${run.id}`);
    } catch (err) {
      setError(err.message || "Failed to start run.");
    }
  };

  return (
    <section className="panel project-panel">
      <h2>Test & Execute</h2>
      <p className="muted">
        Start the flow with a support ticket. This page tracks a single run while live view can
        observe the same run in parallel.
      </p>
      <label className="stack-field">
        Test ticket
        <textarea
          rows={8}
          value={ticket}
          onChange={(event) => setTicket(event.target.value)}
        />
      </label>
      <button type="button" className="btn btn-primary" onClick={onRun}>
        Run flow
      </button>
      {error && <p className="error-text">{error}</p>}
      {runRecord && (
        <div className="run-summary">
          <p className="mono">Run ID: {runRecord.id}</p>
          <p>Status: {runRecord.status}</p>
          <div className="inline-actions">
            <Link className="btn" to={`/project/${projectId}/view/${runRecord.id}`}>
              Open live view for this run
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}

export default ProjectRun;
