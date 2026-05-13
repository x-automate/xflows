import { useParams } from "react-router-dom";
import WorkflowAppShell from "../features/workflow/AppShell";

function ProjectView() {
  const { projectId, runId } = useParams();

  return (
    <div className="project-view">
      <div className="view-banner">
        <div>
          <strong>Live execution view</strong>
          <span>
            {runId ? `Watching run ${runId}` : "Waiting for a run selection."}
          </span>
        </div>
        <span className="badge badge-healthy">LIVE</span>
      </div>
      <WorkflowAppShell projectId={projectId} readOnly autoReplay={!runId} liveRunId={runId} />
    </div>
  );
}

export default ProjectView;
