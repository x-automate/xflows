import { useEffect, useState } from "react";
import { NavLink, Navigate, Outlet, useParams } from "react-router-dom";
import { createProject as createProjectApi, getProject as getProjectApi } from "../lib/api/workflowApi";
import { getProject as getLocalProject, upsertProject } from "../lib/projectStore";

function ProjectLayout() {
  const { projectId } = useParams();
  const [remoteProject, setRemoteProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const project = remoteProject || getLocalProject(projectId);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setRemoteProject(null);
    getProjectApi(projectId)
      .then((remote) => {
        if (!active) return;
        upsertProject(remote);
        setRemoteProject(remote);
      })
      .catch(async () => {
        if (!active) return;
        const local = getLocalProject(projectId);
        if (!local) {
          setRemoteProject(null);
          return;
        }
        try {
          const created = await createProjectApi({
            id: local.id,
            name: local.name,
            description: local.description,
          });
          if (!active) return;
          upsertProject(created);
          setRemoteProject(created);
        } catch {
          if (!active) return;
          setRemoteProject(null);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  if (loading && !project) {
    return <section className="panel">Loading project...</section>;
  }

  if (!project) {
    return <Navigate to="/dashboard" replace />;
  }

  const base = `/project/${projectId}`;

  return (
    <section className="project-shell">
      <div className="project-head">
        <div>
          <h1>{project.name}</h1>
          <p className="muted mono">{project.id}</p>
        </div>
        <nav className="project-tabs">
          <NavLink to={`${base}/flow`}>Flow</NavLink>
          <NavLink to={`${base}/configs`}>Configs</NavLink>
          <NavLink to={`${base}/trigger`}>Trigger</NavLink>
          <NavLink to={`${base}/logs`}>Logs</NavLink>
        </nav>
      </div>
      <Outlet context={{ project }} />
    </section>
  );
}

export default ProjectLayout;
