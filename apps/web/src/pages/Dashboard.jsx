import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject as createProjectApi, listProjects as listProjectsApi } from "../lib/api/workflowApi";
import { createProject, listProjects, upsertProject } from "../lib/projectStore";

function Dashboard() {
  const navigate = useNavigate();
  const [projectName, setProjectName] = useState("Customer Support Agent");
  const [projects, setProjects] = useState(() => listProjects());
  const apiBaseUrl = useMemo(
    () => import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
    []
  );

  useEffect(() => {
    let active = true;
    listProjectsApi()
      .then((items) => {
        if (!active || !Array.isArray(items)) return;
        items.forEach((project) => upsertProject(project));
        setProjects(items);
      })
      .catch(() => {
        if (active) setProjects(listProjects());
      });
    return () => {
      active = false;
    };
  }, []);

  const onCreateProject = async (event) => {
    event.preventDefault();
    let project;
    try {
      const remoteProject = await createProjectApi({ name: projectName });
      project = upsertProject(remoteProject);
    } catch {
      project = createProject(projectName);
    }
    try {
      const remoteProjects = await listProjectsApi();
      setProjects(remoteProjects);
    } catch {
      setProjects(listProjects());
    }
    navigate(`/project/${project.id}/flow`);
  };

  return (
    <section className="panel">
      <h1>Projects</h1>
      <p className="muted">
        Create a project, then move through flow, trigger, logs, run, and live view.
      </p>

      <form className="project-create" onSubmit={onCreateProject}>
        <input
          value={projectName}
          onChange={(event) => setProjectName(event.target.value)}
          placeholder="Customer Support Agent"
        />
        <button type="submit" className="btn btn-primary">
          Create project
        </button>
      </form>

      <div className="grid">
        <article className="stat-card">
          <h2>Environment</h2>
          <p>Development</p>
        </article>
        <article className="stat-card">
          <h2>API Endpoint</h2>
          <p className="mono">{apiBaseUrl}</p>
        </article>
        <article className="stat-card">
          <h2>Current Focus</h2>
          <p>Web shell and live backend status integration</p>
        </article>
      </div>

      {projects.length > 0 && (
        <div className="project-list">
          <h2>Recent projects</h2>
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className="project-row"
              onClick={() => navigate(`/project/${project.id}/flow`)}
            >
              <span>
                <strong>{project.name}</strong>
                <small>{project.id}</small>
              </span>
              <span>Open</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export default Dashboard;
