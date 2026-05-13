import { useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { updateProject as updateProjectApi } from "../lib/api/workflowApi";
import { updateProject } from "../lib/projectStore";

function ProjectConfigs() {
  const { projectId } = useParams();
  const { project } = useOutletContext();
  const secretKey = `xflows_secret_${projectId}_openai`;
  const [configs, setConfigs] = useState(() => ({
    ...project.configs,
    openaiApiKey: sessionStorage.getItem(secretKey) || "",
  }));
  const [saved, setSaved] = useState(false);

  const update = (key, value) => {
    setSaved(false);
    setConfigs((current) => ({ ...current, [key]: value }));
  };

  const [error, setError] = useState("");

  const onSubmit = async (event) => {
    event.preventDefault();
    sessionStorage.setItem(secretKey, configs.openaiApiKey || "");
    const { openaiApiKey, ...projectConfigs } = configs;
    const updates = {
      configs: {
        ...projectConfigs,
        hasOpenAIKey: Boolean(openaiApiKey),
      },
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
        Store project-level provider settings used by the flow during tests and scheduled runs.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <label>
          OpenAI API key
          <input
            type="password"
            value={configs.openaiApiKey || ""}
            placeholder="sk-..."
            onChange={(event) => update("openaiApiKey", event.target.value)}
          />
        </label>
        <label>
          Model
          <select
            value={configs.model}
            onChange={(event) => update("model", event.target.value)}
          >
            <option value="gpt-4o-mini">gpt-4o-mini</option>
            <option value="gpt-4o">gpt-4o</option>
            <option value="gpt-4-turbo">gpt-4-turbo</option>
          </select>
        </label>
        <label>
          Temperature
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={configs.temperature}
            onChange={(event) => update("temperature", Number(event.target.value))}
          />
        </label>
        <label>
          Max tokens
          <input
            type="number"
            value={configs.maxTokens}
            onChange={(event) => update("maxTokens", Number(event.target.value))}
          />
        </label>
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
