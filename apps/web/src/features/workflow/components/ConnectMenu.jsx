import { useEffect, useMemo, useRef, useState } from "react";
import {
  CATEGORY_COLORS,
  XFLOWS_ICONS,
  getComponentMeta,
} from "../catalog/catalog-meta";
import { connectCandidates, filterCandidates } from "../catalog/connect-candidates";

/**
 * The menu a wire opens when it is dropped on empty canvas.
 *
 * A dangling wire used to vanish, which quietly punished the common gesture of
 * pulling a wire out and only then deciding where it goes. Every row here comes
 * from `connectCandidates`, so the menu can only offer connections the canvas
 * would accept: nodes already placed, then components it will drop in and wire
 * up in one step.
 */

const MENU_W = 264;
const MENU_MAX_H = 330;
const GUTTER = 8;

const KIND_LABEL = {
  data: "data",
  error: "error",
  config: "config",
};

function Row({ row, active, onChoose, onHover }) {
  const color = CATEGORY_COLORS[row.category] || CATEGORY_COLORS["I/O"];
  return (
    <button
      type="button"
      className={`wf-connect-row${active ? " active" : ""}`}
      onMouseEnter={onHover}
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => onChoose(row)}
      title={row.desc}
    >
      <span
        className="wf-connect-row-icon"
        style={{ background: color.bg, color: color.fg, borderColor: color.dot }}
        dangerouslySetInnerHTML={{ __html: XFLOWS_ICONS[row.icon] || "" }}
      />
      <span className="wf-connect-row-name">{row.name}</span>
      <span className="wf-connect-row-meta">{row.slot || row.category}</span>
    </button>
  );
}

function ConnectMenu({ pending, nodes, edges, position, bounds, onChoose, onClose }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);

  const { onCanvas, create } = useMemo(
    () => connectCandidates({ nodes, edges, pending }),
    [nodes, edges, pending]
  );
  const visible = useMemo(
    () => ({
      onCanvas: filterCandidates(onCanvas, query),
      create: filterCandidates(create, query),
    }),
    [onCanvas, create, query]
  );
  const flat = useMemo(
    () => [...visible.onCanvas, ...visible.create],
    [visible]
  );

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useEffect(() => {
    setActive(0);
  }, [query]);

  const anchorMeta = getComponentMeta(
    nodes.find((node) => node.id === pending.anchorId)?.componentId
  );
  const reverse = pending.direction === "reverse";
  const kind = pending.kind || "data";

  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current) => (flat.length ? (current + 1) % flat.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => (flat.length ? (current - 1 + flat.length) % flat.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (flat[active]) onChoose(flat[active]);
    }
  };

  const left = Math.max(
    GUTTER,
    Math.min(position.x, Math.max(GUTTER, (bounds?.w || MENU_W) - MENU_W - GUTTER))
  );
  const top = Math.max(
    GUTTER,
    Math.min(position.y, Math.max(GUTTER, (bounds?.h || MENU_MAX_H) - MENU_MAX_H - GUTTER))
  );

  const section = (label, rows, offset) =>
    rows.length > 0 && (
      <div className="wf-connect-group">
        <div className="wf-connect-group-head">
          <span>{label}</span>
          <span className="wf-connect-group-count">{rows.length}</span>
        </div>
        {rows.map((row, index) => (
          <Row
            key={row.key}
            row={row}
            active={offset + index === active}
            onHover={() => setActive(offset + index)}
            onChoose={onChoose}
          />
        ))}
      </div>
    );

  return (
    <>
      <div
        className="wf-connect-backdrop"
        data-testid="wf-connect-backdrop"
        onMouseDown={(event) => {
          event.stopPropagation();
          onClose();
        }}
      />
      <div
        className="wf-connect-menu"
        style={{ left, top, width: MENU_W, maxHeight: MENU_MAX_H }}
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="wf-connect-head">
          <span className={`wf-connect-kind ${kind}`}>{KIND_LABEL[kind] || kind}</span>
          <span className="wf-connect-title">
            {reverse ? "into " : "from "}
            <b>{anchorMeta?.name || "node"}</b>
            {pending.slot ? ` · ${pending.slot}` : ""}
          </span>
        </div>
        <input
          ref={inputRef}
          className="wf-connect-search"
          placeholder="Search nodes..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="wf-connect-list">
          {section("On this canvas", visible.onCanvas, 0)}
          {section("Add a node", visible.create, visible.onCanvas.length)}
          {flat.length === 0 && (
            <div className="wf-connect-empty">
              {query
                ? `Nothing matches "${query}".`
                : "Nothing can take this connection."}
            </div>
          )}
        </div>
        <div className="wf-connect-foot">↑↓ move · Enter connect · Esc cancel</div>
      </div>
    </>
  );
}

export default ConnectMenu;
