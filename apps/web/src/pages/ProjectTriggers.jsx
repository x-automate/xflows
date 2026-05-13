import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  createProjectTrigger,
  listProjectTriggers,
  updateProjectTrigger,
} from "../lib/api/workflowApi";
import { getProjectTriggers, saveProjectTriggers } from "../lib/projectStore";

function createBlankTrigger() {
  return {
    id: `trg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    type: "time",
    enabled: true,
    queue: "support_tickets",
    time: "08:00",
    timezone: "local",
  };
}

function ProjectTriggers() {
  const { projectId } = useParams();
  const [triggers, setTriggers] = useState(() => getProjectTriggers(projectId));
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    listProjectTriggers(projectId)
      .then((items) => {
        if (!active || !Array.isArray(items)) return;
        const hydrated = items.map((trigger) => ({
          ...trigger,
          queue: trigger.config?.queue || "support_tickets",
          time: trigger.config?.time || "08:00",
          timezone: trigger.config?.timezone || "local",
        }));
        setTriggers(hydrated);
      })
      .catch(() => {
        if (active) setTriggers(getProjectTriggers(projectId));
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  const update = (id, key, value) => {
    setSaved(false);
    setTriggers((current) =>
      current.map((trigger) => (trigger.id === id ? { ...trigger, [key]: value } : trigger))
    );
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    setSaved(false);
    setError("");
    try {
      const existing = await listProjectTriggers(projectId);
      const existingById = new Set(existing.map((trigger) => trigger.id));
      const updated = await Promise.all(
        triggers.map((trigger) => {
          const payload = {
            type: trigger.type || "time",
            enabled: Boolean(trigger.enabled),
            config: {
              queue: trigger.queue,
              time: trigger.time,
              timezone: trigger.timezone,
            },
          };
          if (existingById.has(trigger.id)) {
            return updateProjectTrigger(projectId, trigger.id, payload);
          }
          return createProjectTrigger(projectId, payload);
        })
      );
      const hydrated = updated.map((trigger) => ({
        ...trigger,
        queue: trigger.config?.queue || "support_tickets",
        time: trigger.config?.time || "08:00",
        timezone: trigger.config?.timezone || "local",
      }));
      setTriggers(hydrated);
      saveProjectTriggers(projectId, hydrated);
      setSaved(true);
    } catch (err) {
      saveProjectTriggers(projectId, triggers);
      setError(err.message || "Failed to save triggers to API.");
      setSaved(true);
    }
  };

  return (
    <section className="panel project-panel">
      <h2>Triggers</h2>
      <p className="muted">
        Manage all automation triggers for this project and add new schedules as needed.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div className="table-wrap table-span">
          <table className="data-table">
            <thead>
              <tr>
                <th>Enabled</th>
                <th>Queue</th>
                <th>Time</th>
                <th>Timezone</th>
              </tr>
            </thead>
            <tbody>
              {triggers.map((trigger) => (
                <tr key={trigger.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={trigger.enabled}
                      onChange={(event) => update(trigger.id, "enabled", event.target.checked)}
                    />
                  </td>
                  <td>
                    <input
                      value={trigger.queue}
                      onChange={(event) => update(trigger.id, "queue", event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="time"
                      value={trigger.time}
                      onChange={(event) => update(trigger.id, "time", event.target.value)}
                    />
                  </td>
                  <td>
                    <select
                      value={trigger.timezone}
                      onChange={(event) => update(trigger.id, "timezone", event.target.value)}
                    >
                      <option value="local">Local</option>
                      <option value="UTC">UTC</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => setTriggers((current) => [...current, createBlankTrigger()])}
        >
          Add trigger
        </button>
        <button type="submit" className="btn btn-primary">
          Save triggers
        </button>
      </form>
      {saved && <p className="success-text">Triggers saved.</p>}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}

export default ProjectTriggers;
