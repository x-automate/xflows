import { useEffect, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import {
  createProjectTrigger,
  listProjectTriggers,
  updateProjectTrigger,
} from "../lib/api/workflowApi";
import { getProjectTriggers, saveProjectTriggers } from "../lib/projectStore";

const ENTRY_NODE_COMPONENTS = {
  webhook: ["Webhook", "WebhookTrigger"],
  event: ["XWSEventTrigger"],
};

function createBlankTrigger() {
  return {
    id: `trg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    type: "time",
    enabled: true,
    queue: "support_tickets",
    time: "08:00",
    timezone: "local",
    nodeId: "",
  };
}

function entryNodesForType(project, type) {
  const componentIds = ENTRY_NODE_COMPONENTS[type];
  if (!componentIds) return [];
  const nodes = project?.graph?.nodes || [];
  return nodes.filter((node) => componentIds.includes(node.componentId));
}

function hydrateTrigger(trigger) {
  return {
    ...trigger,
    queue: trigger.config?.queue || "support_tickets",
    time: trigger.config?.time || "08:00",
    timezone: trigger.config?.timezone || "local",
    nodeId: trigger.config?.nodeId || "",
  };
}

function ProjectTriggers() {
  const { projectId } = useParams();
  const { project } = useOutletContext();
  const [triggers, setTriggers] = useState(() => getProjectTriggers(projectId));
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    listProjectTriggers(projectId)
      .then((items) => {
        if (!active || !Array.isArray(items)) return;
        setTriggers(items.map(hydrateTrigger));
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

  const onChangeType = (id, type) => {
    const entryNodes = entryNodesForType(project, type);
    update(id, "type", type);
    update(id, "nodeId", entryNodes[0]?.id || "");
  };

  const buildConfig = (trigger) => {
    if (trigger.type === "webhook" || trigger.type === "event") {
      const entryNode = entryNodesForType(project, trigger.type).find(
        (node) => node.id === trigger.nodeId
      );
      const base = {
        workflowId: `wf_${projectId}`,
        nodeId: trigger.nodeId || undefined,
      };
      if (trigger.type === "webhook") {
        return {
          ...base,
          path: entryNode?.params?.path,
          method: entryNode?.params?.method,
          secretHeader: entryNode?.params?.secretHeader,
        };
      }
      return {
        ...base,
        sourceService: entryNode?.params?.sourceService,
        eventType: entryNode?.params?.eventType,
      };
    }
    return {
      queue: trigger.queue,
      time: trigger.time,
      timezone: trigger.timezone,
    };
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
            config: buildConfig(trigger),
          };
          if (existingById.has(trigger.id)) {
            return updateProjectTrigger(projectId, trigger.id, payload);
          }
          return createProjectTrigger(projectId, payload);
        })
      );
      const hydrated = updated.map(hydrateTrigger);
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
        Manage all automation triggers for this project and add new schedules as needed. Webhook
        and XWS Event triggers activate a matching entry node already placed on the Flow canvas
        &mdash; run the flow at least once first so the node is published.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        {triggers.map((trigger) => {
          const entryNodes = entryNodesForType(project, trigger.type);
          const isEntryNodeTrigger = trigger.type === "webhook" || trigger.type === "event";
          return (
            <div key={trigger.id} className="table-wrap table-span trigger-card">
              <div className="inline-actions">
                <label>
                  Enabled
                  <input
                    type="checkbox"
                    checked={trigger.enabled}
                    onChange={(event) => update(trigger.id, "enabled", event.target.checked)}
                  />
                </label>
                <label>
                  Type
                  <select
                    value={trigger.type}
                    onChange={(event) => onChangeType(trigger.id, event.target.value)}
                  >
                    <option value="time">Time</option>
                    <option value="webhook">Webhook</option>
                    <option value="event">XWS Event</option>
                  </select>
                </label>
              </div>

              {trigger.type === "time" && (
                <div className="inline-actions">
                  <label>
                    Queue
                    <input
                      value={trigger.queue}
                      onChange={(event) => update(trigger.id, "queue", event.target.value)}
                    />
                  </label>
                  <label>
                    Time
                    <input
                      type="time"
                      value={trigger.time}
                      onChange={(event) => update(trigger.id, "time", event.target.value)}
                    />
                  </label>
                  <label>
                    Timezone
                    <select
                      value={trigger.timezone}
                      onChange={(event) => update(trigger.id, "timezone", event.target.value)}
                    >
                      <option value="local">Local</option>
                      <option value="UTC">UTC</option>
                    </select>
                  </label>
                </div>
              )}

              {isEntryNodeTrigger && (
                <div className="inline-actions">
                  <label>
                    Entry node
                    <select
                      value={trigger.nodeId}
                      onChange={(event) => update(trigger.id, "nodeId", event.target.value)}
                    >
                      <option value="">Select a node&hellip;</option>
                      {entryNodes.map((node) => (
                        <option key={node.id} value={node.id}>
                          {node.id} ({node.componentId})
                        </option>
                      ))}
                    </select>
                  </label>
                  {entryNodes.length === 0 && (
                    <p className="muted">
                      No {trigger.type === "webhook" ? "Webhook" : "XWS Event"} node found on the
                      Flow canvas yet &mdash; add one before saving this trigger.
                    </p>
                  )}
                </div>
              )}

              {trigger.type === "webhook" && trigger.config?.signatureSecret && (
                <p className="muted">
                  Deliver signed requests to <code>/webhooks/{trigger.id}</code> with header{" "}
                  <code>x-webhook-signature: sha256=&lt;hmac&gt;</code> using secret{" "}
                  <code>{trigger.config.signatureSecret}</code>.
                </p>
              )}

              {trigger.type === "event" && trigger.config?.accessKeyId && (
                <p className="muted">
                  Configure the calling XWS service to SigV4-sign requests to{" "}
                  <code>/events/{trigger.id}</code> with access key{" "}
                  <code>{trigger.config.accessKeyId}</code> and secret{" "}
                  <code>{trigger.config.secretAccessKey}</code>.
                </p>
              )}
            </div>
          );
        })}
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
