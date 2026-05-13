import { useParams } from "react-router-dom";
import WorkflowAppShell from "../features/workflow/AppShell";

function WorkflowEditor() {
  const { projectId } = useParams();
  return <WorkflowAppShell projectId={projectId} />;
}

export default WorkflowEditor;
