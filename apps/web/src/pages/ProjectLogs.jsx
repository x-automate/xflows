import { Fragment, useEffect, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";
import { getRunEventHistory, listProjectRuns } from "../lib/api/workflowApi";
import { getProjectRuns } from "../lib/projectStore";

function toneFor(status) {
  if (status === "succeeded") return "healthy";
  if (status === "running" || status === "queued") return "degraded";
  return "error";
}

function ProjectLogs() {
  const { projectId } = useParams();
  const { project } = useOutletContext();
  const [runs, setRuns] = useState(() => getProjectRuns(projectId));
  const [expandedRunId, setExpandedRunId] = useState(null);
  const [eventHistory, setEventHistory] = useState({});
  const [eventLoading, setEventLoading] = useState({});

  useEffect(() => {
    let active = true;
    listProjectRuns(projectId)
      .then((result) => {
        if (active && Array.isArray(result) && result.length) {
          setRuns(result);
        }
      })
      .catch(() => {
        // Keep local history when API has no persisted runs yet.
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  const toggleRunDetails = async (runId) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
      return;
    }
    setExpandedRunId(runId);
    if (eventHistory[runId]) {
      return;
    }
    setEventLoading((current) => ({ ...current, [runId]: true }));
    try {
      const events = await getRunEventHistory(runId);
      setEventHistory((current) => ({ ...current, [runId]: events }));
    } catch {
      setEventHistory((current) => ({ ...current, [runId]: [] }));
    } finally {
      setEventLoading((current) => ({ ...current, [runId]: false }));
    }
  };

  return (
    <section className="panel project-panel">
      <h2>Run Logs</h2>
      <p className="muted">
        Review previous runs for <strong>{project.name}</strong> and open any run in test or live
        view mode.
      </p>
      {runs.length === 0 ? (
        <p className="muted">No runs yet. Start your first run from the test route.</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Started</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const isOpen = expandedRunId === run.id;
                const details = eventHistory[run.id] || [];
                return (
                  <Fragment key={run.id}>
                    <tr>
                      <td className="mono">{run.id}</td>
                      <td>
                        <span className={`badge badge-${toneFor(run.status)}`}>{run.status}</span>
                      </td>
                      <td>{run.startedAt ? new Date(run.startedAt).toLocaleString() : "—"}</td>
                      <td className="row-actions">
                        <Link to={`/project/${projectId}/run/${run.id}`}>Run</Link>
                        <Link to={`/project/${projectId}/view/${run.id}`}>View</Link>
                        <button type="button" className="btn-link" onClick={() => toggleRunDetails(run.id)}>
                          {isOpen ? "Hide details" : "Details"}
                        </button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={4}>
                          {eventLoading[run.id] ? (
                            <p className="muted small-gap">Loading detailed events...</p>
                          ) : details.length === 0 ? (
                            <p className="muted small-gap">No detailed events captured for this run yet.</p>
                          ) : (
                            <div className="table-wrap run-events-wrap">
                              <table className="data-table run-events-table">
                                <thead>
                                  <tr>
                                    <th>Time</th>
                                    <th>Type</th>
                                    <th>Node</th>
                                    <th>Payload</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {details.map((event, idx) => (
                                    <tr key={`${run.id}_event_${idx}`}>
                                      <td>{new Date(event.timestamp).toLocaleTimeString()}</td>
                                      <td>{event.type}</td>
                                      <td className="mono">{event.nodeId || "—"}</td>
                                      <td className="mono event-payload">
                                        {Object.keys(event.payload || {}).length
                                          ? JSON.stringify(event.payload)
                                          : "—"}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="inline-actions">
        <Link className="btn btn-primary" to={`/project/${projectId}/run/new`}>
          Start new run
        </Link>
      </div>
    </section>
  );
}

export default ProjectLogs;
