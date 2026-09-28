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
- **Nodes** are absolutely-positioned divs: 132×56 px for regular nodes, 200×110 px for
  containers. Each shows its icon (inline SVG from the catalog), name, category, and — during
  runs — a live badge (spinner, duration in ms, or failed marker).
- **Ports** are declared by `catalog/port-model.js` and gated on the component's `kind`, never
  on its category. Every node that executes offers the *same two outputs*, because any
  executor can throw:
  - `in` — left edge, mid-height. Absent on `input` kinds (Input and the triggers).
  - `out` — right edge, mid-height, black. The node's normal result; solid wires.
  - `error-out` — right edge, `ERROR_PORT_DROP` (18px) lower, red. Taken instead when the node
    throws; dashed wires. Present on *every* node that runs — triggers and the terminal
    `Output` included, since an Output that fails to deliver is still a failure worth routing.
  - One structural exception: an `aux` kind (Langfuse, LangSmith, Tracer, Guardrail, Vector DB)
    attaches to a container's config slot rather than to the data flow, so instead of data and
    error bubbles it carries a single config bubble. `Output` is the one node with an error
    output but no data output: it is the terminal sink, so nothing runs after it on success.
  - Category is *not* the gate: `TraceLog` and `ErrorLog` are categorised Observability but
    are ordinary inline transforms with full data ports. Gating on the category stripped them.
  - Config ports: a top-center `config-out` on any node whose category some container slot
    accepts (derived from the registry, not hardcoded), and labeled `config-in` slots along a
    container's bottom edge (declared by the container's `configs`).
  - Bubbles render in their own `.wf-ports-layer` above the nodes, each placed at the canvas
    coordinate `portsForNode()` returns and centred on it with `translate(-50%, -50%)`. The
    stylesheet sets no offsets at all, and `sourcePortPos()` / `targetPortPos()` place the wire
    ends from the same functions, so a wire cannot drift off the bubble it leaves. (It used to:
    a `.wf-port` block declared *after* `.wf-port-error-out` won the cascade on equal
    specificity, which parked every error bubble invisibly under its data bubble while the
    error edge was still drawn 20px below. `workflow-css.test.js` resolves the cascade and
    fails if any rule sets a port offset again.)
  - Port hit-testing uses `document.elementFromPoint` during wire dragging, so connections work
    at any pan/zoom. The port layer is `pointer-events: none` so panning still works through
    it, and dropping a provider on a container's own bubble still nests it in the container.
    A node is dragged by its body — every bubble is a wire origin, not a handle.
- **Edges** are cubic-bezier SVG paths:
  - **Data edges** (default `kind: "data"`): left-in → right-out, black arrow marker.
  - **Error edges** (`kind: "error"`): from the red `error-out` bubble on the node's lower right
    to a target's data-in bubble, red (`#dc2626`) and dashed. Taken when the source node raises. The
    payload delivered is `{"value": "", "error": {message, nodeId, componentId}}` — note the
    blank `value`, which is why a plain `PromptTemplate` on an error branch renders nothing
    useful. Wire the branch into an **Error Log** node instead: it reads the error envelope,
    records a structured entry, and returns the formatted message as its value so the rest of
    the branch has real text.
  - **Config edges**: aux node → container slot, orange (`#c2410c`) vertical bezier, labeled by
    slot name. Config edges are metadata for the designer; the backend executes only data and
    error edges (`normalize_workflow_graph` drops config edges).
  - A pending wire renders as a dashed live path while you drag.
  - Edges can be selected and deleted, and a data/error edge can be re-typed or given a `when`
    predicate in the edge editor popover.

### Wiring

Every bubble starts a wire, in the direction that bubble implies (`portsForNode` carries a
`direction`; `DROP_SELECTOR` in `Canvas.jsx` maps it to what the far end may land on):

| Pulled from | Direction | Looking for | Edge |
|---|---|---|---|
| `out` | forward — the node is the **source** | a target's `in` | data |
| `error-out` | forward | a target's `in` | error |
| `config-out` | forward | a container's `config-in` | config |
| `in` | reverse — the node is the **target** | a source's `out`, or its `error-out` | data, or error if dropped on the red bubble |
| `config-in` | reverse | an aux node's `config-out` | config, into the slot it was pulled from |

A wire released **on a bubble** connects to it; released **on a node body** it connects to that
node's matching bubble (a forward config wire is the exception — with more than one slot the
menu asks which). Released on **empty canvas** it opens the connect menu instead of vanishing.
A click that never pulled the wire more than 4px is not a drop, so a stray click on a bubble
does nothing.

### Connect menu

`components/ConnectMenu.jsx`, fed by `catalog/connect-candidates.js`.

- Opens where the wire was let go, holding the wire on screen (dimmed) so the choice still reads
  as "this wire goes to …". It lives in the canvas wrap, not the transformed inner layer, so it
  keeps its size at any zoom, and it is clamped to stay inside the canvas.
- **On this canvas** lists the nodes the wire may legally join; **Add a node** lists the
  components it can create *and* wire in one commit — so one undo takes back both. Both lists
  come from running the real `checkConnection` gate (against a probe node for the components),
  so the menu can never offer a connection the canvas would then refuse. Providers and
  `planned` components are left out of the create list: neither can stand on its own.
- A config wire lists one row per slot that accepts the source, labelled with the slot name.
- A created node is placed by `nodeOriginForPort` so the bubble the wire needs lands exactly on
  the wire's loose end.
- Type to filter, `↑`/`↓` to move, `Enter` to connect, `Esc` or a click on the backdrop to cancel.

### Connection rules

`catalog/connection-rules.js` gates every connection **before** the edge is created; a refused
connection flashes the reason as a toast and nothing is drawn. `checkConnection` refuses:

| Rule | Applies to |
|---|---|
| target is an `input`-kind node | data, error |
| source is an `output`-kind node | data only — an Output can still route its own failure |
| either end is an Observability node (they attach to config slots) | data, error |
| either end is a nested provider (wire the container instead) | data, error, config |
| source and target are the same node | all |
| an identical edge already exists (same pair, kind and slot) | all |
| the edge would close a cycle (config edges excluded) | data, error |
| the slot does not exist on the target | config |
| the source's category is not in the slot's `accepts` | config |

`hooks/useWorkflowValidation.js` still runs the whole-graph checks (single Input/Output,
orphan nodes, one provider per container, planned components) and reports them in the
Validation tab — it catches graphs loaded from JSON, which never pass through the canvas gate.

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

- Search box filters by component name, id, category or description.
- Components are grouped by category, each with its colored dot, name, and per-group count.
- Tooltip shows the component description.
- Double-click adds the component; drag places it precisely.

See the [node catalog](node-catalog.md) for the full list of the 42 components.

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
