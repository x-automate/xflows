# Workflow Editor

The editor is a fully custom SVG+DOM canvas (no flow library) built in
`apps/web/src/features/workflow/`. The orchestrator is `AppShell.jsx`, which owns graph state,
history, run lifecycle, and toasts.

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Topbar: Dashboard · Workflow Editor · Status                     │
├──────────┬──────────────────────────────────────────┬────────────┤
│ Component│                Canvas                    │ Steps Pane │
│ Panel    │   (pan/zoom, nodes, wires)               │ Properties │
│ (left)   │                                          │ Steps      │
│          │                                          │ Test       │
│          │                                          │ Validation │
└──────────┴──────────────────────────────────────────┴────────────┘
```

## Canvas

Implemented in `components/Canvas.jsx`.

- **Pan**: drag the background. **Zoom**: `Ctrl/Cmd + wheel` (0.4×–2×, anchored at the cursor) or
  the `+ / − / Reset` controls; plain wheel scrolls. Zoom % is shown in the canvas controls.
- The viewport is applied as `transform: translate(x, y) scale(k)` on the canvas inner element;
  a 6000×6000 SVG layer holds all edges; a grid background scales with zoom.
- **Nodes** are absolutely-positioned divs: 132×46 px for regular nodes, 200×110 px for
  containers. Each shows its icon (inline SVG from the catalog), name, category, and — during
  runs — a live badge (spinner, duration in ms, or failed marker).
- **Ports**:
  - Data ports: `in` (left side) and `out` (right side) of every node.
  - Config ports: a top-center `config-out` on Observability/Memory/Tool aux nodes, and labeled
    `config-in` slots along a container's bottom edge (declared by the container's `configs`).
  - Port hit-testing uses `document.elementFromPoint` during wire dragging, so connections work
    at any pan/zoom.
- **Edges** are cubic-bezier SVG paths:
  - **Data edges** (default `kind: "data"`): left-in → right-out, black arrow marker.
  - **Config edges**: aux node → container slot, orange (`#c2410c`) vertical bezier, labeled by
    slot name. Config edges are metadata for the designer; the backend executes only data edges.
  - A pending wire renders as a dashed live path while you drag.
  - Duplicate edges are prevented; edges can be selected and deleted (ids starting with `e_`).

## Containers and Providers

The `LLM` component is a **container**. Providers (`OpenAIChat`, `AnthropicChat`, `LiteLLM`)
render as an inner chip of their container:

- Dropping a provider onto the container (or onto the "Drop a provider here" placeholder) nests
  it as a child node — allowed only if the container's `accepts` includes the provider's
  category, and only **one provider per container** is allowed.
- The provider chip has a remove button.
- At run time, graph normalization **promotes** the provider into the container: the merged node
  takes the child's `componentId` and merges params (child wins), so provider params are what the
  executor sees. See [node execution reference](../reference/node-execution.md#graph-normalization).

## Drag & Drop

- The Component Panel items are HTML5 draggable (`dataTransfer: "component-id"`); dropping on the
  canvas computes canvas-space coordinates from the current pan/zoom.
- Double-clicking a palette item adds the component at a cascade offset.
- Nodes move by mouse drag (position changes are not part of undo history).
- Dropping a node onto a container auto-nests it when the container accepts its category.

## Component Panel

`components/ComponentPanel.jsx`:

- Search box filters by component name.
- Components are grouped by category, each with its colored dot, name, and per-group count.
- Tooltip shows the component description.
- Double-click adds the component; drag places it precisely.

See the [node catalog](node-catalog.md) for the full list of the 36 components.

## Parameter Editing

- **Properties panel** (`components/PropertiesPanel.jsx`): shows when a node is selected; every
  change is saved immediately.
- **ParamModal** (`components/ParamModal.jsx`): opened by double-clicking a canvas node or the ⚙
  button in the Steps tab; explicit **Save parameters**; closes on Escape/backdrop.
- Field types are driven by the catalog's param schema: `select` (options), `number` (step),
  `text`, `textarea`, `bool` (checkbox). Defaults and `help` text are shown from the catalog.

## Steps Pane

`components/StepsPane.jsx` — four tabs:

1. **Properties** — the inline properties editor for the selected node.
2. **Steps** — nodes in topological execution order, each with a step number, category dot, up
   to 3 param pills (`name=value`), ⚙ to open ParamModal, and ✕ to delete.
3. **Test** — test-input textarea, **Run workflow** button (disabled while invalid or running),
   a scrolling execution trace (start/success/error rows with durations, `provider=`/`model=`
   metadata, truncated output), and the final output block. See [Runs](runs.md#test-runs-from-the-editor).
4. **Validation** — the list of validation errors, or "Workflow is valid".

## Validation

Implemented in `hooks/useWorkflowValidation.js` (`topoSort` + memoized `validateWorkflow`):

- Canvas must not be empty.
- The data-edge graph must be acyclic (Kahn's algorithm; also yields the Steps ordering).
- Exactly one `Input` and exactly one `Output` node.
- `Input` has no incoming data edges; `Output` has no outgoing data edges.
- Unconnected nodes are flagged.
- Provider components must sit inside a container that accepts them; containers have at most one
  child.
- Config edges must target a valid declared slot, and the slot's `accepts` must include the
  source component's category.

Runs are blocked while validation fails.

## History and Shortcuts

- **Undo/redo** stacks (`{past, future}`) are capped at 50 entries and cover graph mutations
  (add/connect/delete params and structural edits). Node drags are not history-committed.
- Keyboard shortcuts (window-level in `AppShell.jsx`, skipped while typing in inputs):

| Keys | Action |
|---|---|
| `Delete` / `Backspace` | Delete selection (node or edge) |
| `Ctrl/Cmd + D` | Duplicate selection |
| `Ctrl/Cmd + Z` | Undo |
| `Ctrl/Cmd + Shift + Z` or `Ctrl + Y` | Redo |

- **Clear all** empties the canvas after a confirm prompt.

## JSON Import/Export

- **Export**: downloads the graph as `workflow.json` (an object of `{nodes, edges}`).
- **Import**: reads a JSON file back in with validation; invalid files are rejected with a toast.

There is no code-generation export: the original POC's browser codegen was replaced by backend
orchestration (see root README migration map). The JSON file is the interchange format and
matches the shape consumed by `POST /projects/:id/runs` (see
[API reference](../reference/api-reference.md)).

## Run Visualization

During a run the editor consumes SSE events and updates the canvas:

- `node_started` → node badge becomes a spinner (event type `start`).
- `node_succeeded` → badge shows duration in ms; the outgoing data edge to the next topological
  node gets a brief (800 ms) animated "flow" overlay (`activeEdges`).
- `node_failed` → badge shows the failed marker; a toast flashes the error.
- Per-node statuses, durations, metadata, and the final output are kept in `runState`.

The same component tree powers the read-only **live view** (`readOnly`, bound to a `liveRunId`)
and demo **autoReplay** playback — see [Runs](runs.md#live-view).

## Standalone vs Project Editor

- `/editor` runs the editor without a project binding (standalone test runs create throwaway
  workflows `wf_web_editor_<timestamp>`).
- `/project/:id/flow` scopes the same editor to the project: graph autosave targets
  `PATCH /projects/:id`, and test runs submit the project workflow snapshot plus the project's
  runtime config.
