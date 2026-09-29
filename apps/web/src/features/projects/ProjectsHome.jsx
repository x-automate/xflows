import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createProject as createProjectApi,
  listProjectRuns,
  listProjectTriggers,
  listProjects as listProjectsApi,
  updateProject as updateProjectApi,
} from "../../lib/api/workflowApi";
import {
  createProject as createLocalProject,
  listProjects as listLocalProjects,
  updateProject as updateLocalProject,
  updateProjectGraph,
  upsertProject,
} from "../../lib/projectStore";
import NewProjectModal from "./NewProjectModal";
import {
  aggregateTotals,
  filterProjects,
  formatCount,
  formatRate,
  isProjectActive,
  metadataWithActive,
  rateColor,
  relativeTime,
  summariseRuns,
  triggerLabels,
} from "./projectStats";
import "./projects.css";

const FILTERS = ["all", "active", "paused"];

/** `null` means the request failed; `[]` means the project genuinely has none. */
const UNKNOWN = { runs: null, triggers: null };

function ProjectsHome() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState(() => listLocalProjects());
  const [details, setDetails] = useState({});
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    listProjectsApi()
      .then((items) => {
        if (!active || !Array.isArray(items)) return;
        items.forEach((project) => upsertProject(project));
        setProjects(items);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setProjects(listLocalProjects());
        setError("Showing projects saved in this browser — the API is unreachable.");
      });
    return () => {
      active = false;
    };
  }, []);

  // Runs and triggers are per-project endpoints, so the stats columns cost one
  // pair of requests per row. Keyed on the id list rather than on `projects`
  // so that pausing a project does not refetch every project's run history.
  const projectIds = useMemo(() => projects.map((project) => project.id).join(","), [projects]);

  useEffect(() => {
    let active = true;
    const ids = projectIds ? projectIds.split(",") : [];
    if (!ids.length) {
      setDetails({});
      return undefined;
    }
    Promise.all(
      ids.map(async (id) => {
        const [runs, triggers] = await Promise.all([
          listProjectRuns(id).catch(() => null),
          listProjectTriggers(id).catch(() => null),
        ]);
        return [id, { runs: Array.isArray(runs) ? runs : null, triggers: Array.isArray(triggers) ? triggers : null }];
      })
    ).then((entries) => {
      if (active) setDetails(Object.fromEntries(entries));
    });
    return () => {
      active = false;
    };
  }, [projectIds]);

  const rows = useMemo(
    () =>
      filterProjects(projects, { query, filter }).map((project) => {
        const detail = details[project.id] || UNKNOWN;
        return {
          project,
          active: isProjectActive(project),
          summary: summariseRuns(detail.runs, project),
          triggers: detail.triggers === null ? null : triggerLabels(detail.triggers),
        };
      }),
    [projects, details, query, filter]
  );

  const totals = useMemo(
    () =>
      aggregateTotals(
        projects.map((project) => ({
          active: isProjectActive(project),
          summary: summariseRuns((details[project.id] || UNKNOWN).runs, project),
        }))
      ),
    [projects, details]
  );

  const counts = useMemo(
    () => ({
      active: projects.filter((project) => isProjectActive(project)).length,
      paused: projects.filter((project) => !isProjectActive(project)).length,
    }),
    [projects]
  );

  const openProject = (projectId) => navigate(`/project/${projectId}/flow`);

  const toggleActive = async (project) => {
    const metadata = metadataWithActive(project, !isProjectActive(project));
    setProjects((items) =>
      items.map((item) => (item.id === project.id ? { ...item, metadata } : item))
    );
    try {
      upsertProject(await updateProjectApi(project.id, { metadata }));
    } catch {
      updateLocalProject(project.id, { metadata });
    }
  };

  const createProject = async ({ id, name, description, template }) => {
    setCreating(false);
    let project;
    try {
      project = upsertProject(await createProjectApi({ id, name, description }));
    } catch {
      project = createLocalProject(name, id);
      if (description) project = updateLocalProject(project.id, { description });
    }

    // A project with no graph gets the editor's STARTER flow on first open, so
    // "LLM starter" is the do-nothing case and "Blank canvas" is the one that
    // has to write an explicitly empty graph to opt out of it.
    if (template === "blank") {
      const graph = { nodes: [], edges: [] };
      updateProjectGraph(project.id, graph);
      try {
        await updateProjectApi(project.id, { graph });
      } catch {
        // The local graph is enough to open an empty canvas; the editor
        // autosaves it to the API on the first edit.
      }
    }

    openProject(project.id);
  };

  return (
    <section className="ph-page">
      <div className="ph-title-row">
        <div>
          <h1 className="ph-title">Projects</h1>
          <div className="ph-sub">
            Each project holds one workflow with its own configs, triggers and run history.
          </div>
        </div>
        <button type="button" className="ph-btn-primary" onClick={() => setCreating(true)}>
          + New project
        </button>
      </div>

      {error && <div className="ph-error">{error}</div>}

      <div className="ph-stats">
        <div className="ph-stat">
          <div className="ph-stat-value">{formatCount(totals.projects)}</div>
          <div className="ph-stat-key">projects</div>
        </div>
        <div className="ph-stat">
          <div className="ph-stat-value">
            <span className="ph-live-dot" />
            {formatCount(totals.active)}
          </div>
          <div className="ph-stat-key">active</div>
        </div>
        <div className="ph-stat">
          <div className="ph-stat-value">{formatCount(totals.runs)}</div>
          <div className="ph-stat-key">total runs</div>
        </div>
        <div className="ph-stat">
          <div className="ph-stat-value">{formatRate(totals.rate)}</div>
          <div className="ph-stat-key">success rate</div>
        </div>
      </div>

      <div className="ph-toolbar">
        <input
          className="ph-search"
          placeholder="Search by name or UUID…"
          aria-label="Search projects"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="ph-seg" role="group" aria-label="Filter projects">
          {FILTERS.map((name) => (
            <button
              type="button"
              key={name}
              className={filter === name ? "ph-on" : ""}
              aria-pressed={filter === name}
              onClick={() => setFilter(name)}
            >
              {name}
              {name !== "all" && <span className="ph-seg-count">{counts[name]}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="ph-list">
        <div className="ph-list-head">
          <span>Project</span>
          <span>Status</span>
          <span>Runs</span>
          <span>Success</span>
          <span>Last run</span>
          <span>Triggers</span>
          <span />
        </div>

        {rows.map(({ project, active, summary, triggers }) => (
          <div
            key={project.id}
            role="button"
            tabIndex={0}
            className={`ph-row${active ? "" : " ph-paused"}`}
            onClick={() => openProject(project.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openProject(project.id);
              }
            }}
          >
            <div className="ph-row-name">
              <div className="ph-row-title">{project.name}</div>
              <div className="ph-row-desc">{project.description || "No description"}</div>
              <code className="ph-row-id">{project.id}</code>
            </div>

            <div className="ph-row-status" onClick={(event) => event.stopPropagation()}>
              <button
                type="button"
                className={`ph-flag ${active ? "ph-on" : "ph-off"}`}
                title={active ? "Pause project" : "Activate project"}
                onClick={() => toggleActive(project)}
              >
                <span className="ph-flag-dot" />
                {active ? "Active" : "Paused"}
              </button>
            </div>

            <div className="ph-row-runs" data-label="Runs">
              <span className="ph-num">{formatCount(summary.total)}</span>
              {summary.failed > 0 && (
                <span className="ph-fail">{formatCount(summary.failed)} failed</span>
              )}
            </div>

            <div className="ph-row-rate" data-label="Success">
              {summary.rate == null ? (
                <span className="ph-muted">—</span>
              ) : (
                <>
                  <span className="ph-num">{formatRate(summary.rate)}</span>
                  <span className="ph-bar">
                    <span
                      style={{
                        width: `${summary.rate * 100}%`,
                        background: rateColor(summary.rate),
                      }}
                    />
                  </span>
                </>
              )}
            </div>

            <div className="ph-row-last" data-label="Last run">
              {relativeTime(summary.lastRunAt)}
            </div>

            <div className="ph-row-triggers" data-label="Triggers">
              {triggers === null && <span className="ph-muted">—</span>}
              {triggers?.length === 0 && <span className="ph-muted">none</span>}
              {triggers?.map((label) => (
                <span className="ph-chip" key={label}>
                  {label}
                </span>
              ))}
            </div>

            <div className="ph-row-go" aria-hidden="true">
              →
            </div>
          </div>
        ))}

        {rows.length === 0 && (
          <div className="ph-empty">
            {projects.length === 0
              ? "No projects yet."
              : "No projects match these filters."}
            <button
              type="button"
              className="ph-btn-ghost ph-sm"
              onClick={() => setCreating(true)}
            >
              + New project
            </button>
          </div>
        )}
      </div>

      {creating && (
        <NewProjectModal onClose={() => setCreating(false)} onCreate={createProject} />
      )}
    </section>
  );
}

export default ProjectsHome;
