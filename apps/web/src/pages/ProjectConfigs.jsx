import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { updateProject as updateProjectApi } from "../lib/api/workflowApi";
import { getProject as getLocalProject, updateProject } from "../lib/projectStore";
import { getRequiredProjectConfigs } from "../features/workflow/catalog/catalog-meta";

function ProjectConfigs() {
  const { projectId } = useParams();
  const { project } = useOutletContext();
  const localProject = useMemo(
    () => getLocalProject(projectId),
    [projectId, project?.updatedAt]
  );
  const graphNodes = localProject?.graph?.nodes || project?.graph?.nodes || [];
  const requiredConfigs = useMemo(
    () => getRequiredProjectConfigs(graphNodes),
    [graphNodes]
  );
  const [configs, setConfigs] = useState(() => ({ ...(project.configs || {}) }));
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setConfigs((current) => {
      const next = { ...current };
      let changed = false;
      for (const requirement of requiredConfigs) {
        if (!(requirement.key in next) && requirement.default !== undefined) {
          next[requirement.key] = requirement.default;
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [requiredConfigs]);

  const update = (key, value) => {
    setSaved(false);
    setConfigs((current) => ({ ...current, [key]: value }));
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    const updates = {
      configs: configs,
    };
    updateProject(projectId, updates);
    try {
      await updateProjectApi(projectId, updates);
      setError("");
      setSaved(true);
    } catch (err) {
      setError(err.message || "Failed to sync configs with API.");
      setSaved(true);
    }
  };

  return (
    <section className="panel project-panel">
      <h2>Credentials & Global Model Parameters</h2>
      <p className="muted">
        Required fields are derived from nodes currently present in your flow.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        {requiredConfigs.length === 0 && (
          <p className="muted">
            No node-specific global configs are required for the current flow.
          </p>
        )}
        {requiredConfigs.map((config) => {
          const currentValue =
            configs[config.key] ?? config.default ?? "";
          if (config.type === "select") {
            return (
              <label key={config.key}>
                {config.label}
                <select
                  required={Boolean(config.required)}
                  value={currentValue}
                  onChange={(event) => update(config.key, event.target.value)}
                >
                  {(config.options || []).map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                {config.help && <span className="muted">{config.help}</span>}
              </label>
            );
          }
          if (config.type === "number") {
            return (
              <label key={config.key}>
                {config.label}
                <input
                  type="number"
                  required={Boolean(config.required)}
                  value={currentValue}
                  step={config.step || 1}
                  min={config.min}
                  max={config.max}
                  onChange={(event) =>
                    update(
                      config.key,
                      event.target.value === "" ? "" : Number(event.target.value)
                    )
                  }
                />
                {config.help && <span className="muted">{config.help}</span>}
              </label>
            );
          }
          return (
            <label key={config.key}>
              {config.label}
              <input
                type={config.type === "password" ? "password" : "text"}
                required={Boolean(config.required)}
                value={currentValue}
                placeholder={config.placeholder || ""}
                onChange={(event) => update(config.key, event.target.value)}
              />
              {config.help && <span className="muted">{config.help}</span>}
            </label>
          );
        })}
        <button type="submit" className="btn btn-primary">
          Save configs
        </button>
      </form>
      {saved && <p className="success-text">Configs saved for this project.</p>}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}

export default ProjectConfigs;
