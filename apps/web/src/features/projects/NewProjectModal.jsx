import { useEffect, useState } from "react";

function newUuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    return (char === "x" ? random : (random & 3) | 8).toString(16);
  });
}

/**
 * The id is generated here rather than by the API so the modal can show it
 * before the project exists — POST /projects accepts a caller-supplied id.
 */
function NewProjectModal({ onClose, onCreate }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("blank");
  const [id] = useState(newUuid);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const submit = () => {
    if (!name.trim()) return;
    onCreate({ id, name: name.trim(), description: description.trim(), template });
  };

  return (
    <div className="ph-modal-backdrop" onClick={onClose}>
      <div
        className="ph-modal"
        role="dialog"
        aria-modal="true"
        aria-label="New project"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="ph-modal-head">
          <div className="ph-modal-title">New project</div>
          <button type="button" className="ph-x-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="ph-modal-body">
          <div className="ph-field">
            <label htmlFor="ph-new-name">
              <span className="ph-field-name">name</span>
            </label>
            <input
              id="ph-new-name"
              type="text"
              autoFocus
              placeholder="Customer Support Agent"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
            />
          </div>

          <div className="ph-field">
            <label htmlFor="ph-new-description">
              <span className="ph-field-name">description</span>
              <span className="ph-field-default">optional</span>
            </label>
            <input
              id="ph-new-description"
              type="text"
              placeholder="What does this workflow do?"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
            />
          </div>

          <div className="ph-field">
            <div className="ph-field-label">
              <span className="ph-field-name">start from</span>
            </div>
            <div className="ph-template-pick">
              <button
                type="button"
                className={template === "blank" ? "ph-on" : ""}
                aria-pressed={template === "blank"}
                onClick={() => setTemplate("blank")}
              >
                <b>Blank canvas</b>
                <span>Build the flow from scratch</span>
              </button>
              <button
                type="button"
                className={template === "starter" ? "ph-on" : ""}
                aria-pressed={template === "starter"}
                onClick={() => setTemplate("starter")}
              >
                <b>LLM starter</b>
                <span>Input → Prompt → LLM → Output</span>
              </button>
            </div>
          </div>

          <div className="ph-field">
            <div className="ph-field-label">
              <span className="ph-field-name">project id</span>
              <span className="ph-field-default">generated</span>
            </div>
            <code className="ph-new-uuid">{id}</code>
            <div className="ph-field-help">
              You&apos;ll be redirected to /project/{id.slice(0, 8)}…/flow
            </div>
          </div>
        </div>

        <div className="ph-modal-foot">
          <button type="button" className="ph-btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="ph-btn-primary"
            disabled={!name.trim()}
            onClick={submit}
          >
            Create project
          </button>
        </div>
      </div>
    </div>
  );
}

export default NewProjectModal;
