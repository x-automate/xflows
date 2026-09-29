import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import ProjectConfigs from "./pages/ProjectConfigs";
import ProjectLayout from "./pages/ProjectLayout";
import ProjectLogs from "./pages/ProjectLogs";
import ProjectRun from "./pages/ProjectRun";
import ProjectTriggers from "./pages/ProjectTriggers";
import ProjectView from "./pages/ProjectView";
import Projects from "./pages/Projects";
import Status from "./pages/Status";
import WorkflowEditor from "./pages/WorkflowEditor";

function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">XFlows</div>
        <nav className="nav">
          <NavLink to="/projects" className="nav-link">
            Projects
          </NavLink>
          <NavLink to="/editor" className="nav-link">
            Workflow Editor
          </NavLink>
          <NavLink to="/status" className="nav-link">
            Status
          </NavLink>
        </nav>
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/dashboard" element={<Navigate to="/projects" replace />} />
          <Route path="/editor" element={<WorkflowEditor />} />
          <Route path="/status" element={<Status />} />
          <Route path="/project/:projectId" element={<ProjectLayout />}>
            <Route index element={<Navigate to="flow" replace />} />
            <Route path="flow" element={<WorkflowEditor />} />
            <Route path="flows" element={<Navigate to="../flow" replace />} />
            <Route path="configs" element={<ProjectConfigs />} />
            <Route path="trigger" element={<ProjectTriggers />} />
            <Route path="triggers" element={<Navigate to="../trigger" replace />} />
            <Route path="logs" element={<ProjectLogs />} />
            <Route path="run" element={<Navigate to="../logs" replace />} />
            <Route path="run/:runId" element={<ProjectRun />} />
            <Route path="view" element={<Navigate to="../logs" replace />} />
            <Route path="view/:runId" element={<ProjectView />} />
          </Route>
        </Routes>
      </main>
    </div>
  );
}

export default App;
