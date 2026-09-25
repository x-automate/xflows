# Navigation & Tabs — Redesign Proposal

Status: **proposal, not implemented.** This is the design half of the
[platform audit](../reference/platform-audit.md); the audit's defect fixes
shipped, this has not. It is written to be argued with before any of it is built.

## 1. What exists today

Three independent navigation systems, none aware of the others:

```
┌─ Global nav ────────────────────────────────────────────────────┐
│  Dashboard   |   Workflow Editor   |   Status                   │
└─────────────────────────────────────────────────────────────────┘
        │                  │                      │
        │          (no project context —          │
        │           edits a throwaway graph)      │
        ▼                                         ▼
┌─ Project tabs ──────────────────┐      ┌─ System status ─┐
│  Flow | Configs | Trigger | Logs│      │  API + Temporal │
└─────────────────────────────────┘      └─────────────────┘
        │
        ├── Flow ──▶ ┌─ Editor right-pane tabs ──────────────────┐
        │            │ Properties | Steps | Test | Validation    │
        │            └───────────────────────────────────────────┘
        └── Logs ──▶ Run (/run/:id) and Live View (/view/:id)
                     — reachable only from a table row, no tab
```

## 2. What is wrong with it

These are concrete, not stylistic.

**a. Running a workflow lives in three different places.**
The editor's *Test* tab (`StepsPane`) runs the graph through
`POST /workflows/{id}/runs`. The *Run* page (`ProjectRun`) runs the same graph
through `POST /projects/{id}/runs`, with a different input box, a different
default input ("Customer ticket: …" vs "What is the capital of France?"), and a
different result view. *Live View* (`ProjectView`) is a third. A user who wants
to "run this thing" has to know which one to pick, and the answer is not
guessable.

**b. Run and Live View have no tab.**
Both are real routes (`/run/:runId`, `/view/:runId`) but the tab bar shows only
Flow / Configs / Trigger / Logs. They are reachable only by clicking a row in
the Logs table. `/run` and `/view` without an id redirect to Logs. So two of
the six project screens are effectively hidden.

**c. `/editor` has no project.**
The global "Workflow Editor" link mounts `WorkflowAppShell` with
`projectId === undefined`. Nothing autosaves, the Configs tab it would need
does not exist in that context, and running it creates an orphan workflow
`wf_web_editor_<timestamp>`. It is a scratchpad presented as a peer of
Dashboard.

**d. Two levels of tabs on the Flow screen.**
Project tabs across the top, editor tabs down the right, and the right-hand set
silently switches itself to *Properties* whenever you select a node
(`useEffect` on `selectedNode`) — so you cannot keep *Test* open while you
adjust a node, which is exactly the loop authoring a workflow requires.

**e. Validation is a tab you have to visit.**
Errors only surface with a count badge. The Run button disables itself when
`errors.length > 0` with a one-line "Fix validation errors before running", but
the reasons are on another tab, and nothing on the canvas points at the
offending node.

**f. Dashboard is a project picker named Dashboard.**
Three hardcoded stat cards (`Environment: Development`, the API URL, and
`Current Focus: Web shell and live backend status integration` — a developer
note shipped as product copy). No run counts, no failures, no activity.

**g. Status is a whole top-level destination for two fields.**
`/health` returns `{status, temporal}`. It occupies a third of the global nav.

**h. Configs is where you go to fix a problem you were told about elsewhere.**
Required configs are derived from the nodes in the flow, which is good. But
you find out you need a LiteLLM key by having a run fail, then navigating to a
different tab, then coming back.

## 3. Proposed structure

Two levels instead of three, organised around **author → run → observe**, which
is the actual loop.

```
┌─ App bar ───────────────────────────────────────────────────────────┐
│  XFlows   [Project ▾]                        ● API ok  ● Temporal   │
├─────────────────────────────────────────────────────────────────────┤
│  Build   │   Runs   │   Settings                                    │
└─────────────────────────────────────────────────────────────────────┘
```

**Project switcher in the app bar**, not a separate Dashboard destination.
A dropdown listing projects + "New project", with the projects *page* still
reachable at `/projects` for management (rename, delete, duplicate).

**Health as two dots in the app bar**, polling `/health` on the existing 10s
interval, expanding to today's Status card on click. Removes a top-level
destination that carries two fields.

### Build

The canvas, full width, with one docked inspector on the right — and **no tab
switching inside it**. The current four tabs collapse into two stacked regions:

```
┌────────────┬────────────────────────────────┬──────────────────────┐
│ Node       │                                │ ▸ Inspector          │
│ palette    │           Canvas               │   (selected node,    │
│            │                                │    or graph summary) │
│            │                                ├──────────────────────┤
│            │                                │ ▸ Issues        (2)  │
├────────────┴────────────────────────────────┴──────────────────────┤
│ ▸ Run panel — input, trace, output        [Run ▸]   collapsed by ␣ │
└────────────────────────────────────────────────────────────────────┘
```

- **Inspector** replaces *Properties* + *Steps*. Selecting a node shows its
  params; selecting nothing shows the ordered step list. These were never two
  things — *Steps* is the same list the inspector needs a header for.
- **Issues** replaces *Validation* as an always-visible collapsible strip, not
  a tab you can be unaware of. Each row selects and centres the offending node
  on the canvas. Errors get a red ring on the node itself.
- **Run panel** replaces the *Test* tab as a **bottom drawer**, so the trace is
  visible while you edit — the thing the current auto-switch-to-Properties
  behaviour makes impossible. It is the *only* place a run starts.

### Runs

Absorbs today's Logs, Run and Live View into one screen with a master/detail
split, which is what they already are:

```
┌──────────────────┬─────────────────────────────────────────────────┐
│ run_a1b2  ✓ 1.2s │  ▸ Graph     — live node states, active edges   │
│ run_c3d4  ✕      │  ▸ Timeline  — per-node events, durations       │
│ run_e5f6  ⏸ wait │  ▸ Input / Output                               │
│ run_g7h8  ✓      │  ▸ [Approve] [Request changes] [Reject]         │
└──────────────────┴─────────────────────────────────────────────────┘
```

- The list is today's Logs table plus status filters and a live/finished split.
- The **Graph** view is today's `ProjectView` (`readOnly` + `liveRunId`), which
  already does live node states over SSE — it just needs to stop being a
  separate URL.
- The **Timeline** is today's expanded-row event table, made primary.
- **Approval actions belong here.** The endpoints already exist
  (`POST /runs/{id}/approve|reject|request-changes`) and nothing in the web app
  calls them. A run parked on an Approval node is exactly a run you are looking
  at in this list. This is the single highest-value addition in the proposal:
  small, and it turns a `working` node from unusable into usable.
- Deep links stay: `/project/:id/runs/:runId`.

### Settings

Today's Configs and Trigger, as sections of one screen rather than two tabs —
they are both "things configured once per project", and neither fills a screen.
Add a **Secrets** section (`GET`/`PUT /projects/{id}/secrets` exist and have no
UI) and project management (rename, delete — `DELETE /projects/{id}` exists and
has no UI).

Required configs should also surface **where the problem is**: a node whose
`projectConfigs` are unset gets a badge on the canvas linking straight to the
field, instead of a run failing and the user going to find it.

## 4. Route migration

| Today | Proposed | Note |
|---|---|---|
| `/dashboard` | `/projects` | plus app-bar switcher |
| `/editor` | — | remove; scratch work is a project |
| `/status` | app bar | keep `/status` as a redirect |
| `/project/:id/flow` | `/project/:id/build` | alias `flow` |
| `/project/:id/configs` | `/project/:id/settings#configs` | alias |
| `/project/:id/trigger` | `/project/:id/settings#triggers` | alias |
| `/project/:id/logs` | `/project/:id/runs` | alias |
| `/project/:id/run/:runId` | `/project/:id/runs/:runId` | |
| `/project/:id/view/:runId` | `/project/:id/runs/:runId` (Graph) | |

`App.jsx` already keeps redirect aliases for renamed routes (`flows` → `flow`,
`triggers` → `trigger`), so this follows an established pattern and no existing
link breaks.

## 5. What this needs from the API

Small, and mostly additive:

- `GET /runs?limit=&status=` — cross-project run list. Run listing is
  per-project only today, so a global activity feed is an N+1 over projects.
- `GET /projects/{id}/stats` — run counts by status over a window, for the
  project card and the Build header. Derivable client-side from
  `/projects/{id}/runs`, so this is an optimisation, not a blocker.

Everything else the proposal needs already exists.

## 6. Suggested order

Each step is independently shippable and independently useful.

1. **Approval actions on the run detail view.** Endpoints exist, node is
   `working`, currently unusable. Highest value per hour of work.
2. **Merge Logs / Run / Live View into Runs.** Removes the "which run button?"
   confusion and un-hides two screens.
3. **Inspector + Issues, drop the right-pane tabs.** Fixes the
   cannot-watch-the-trace-while-editing loop.
4. **Project switcher + health dots in the app bar; retire `/editor`.**
5. **Settings screen with Secrets and project management.**
6. **A real dashboard**, once `GET /runs` exists.

Steps 1 and 2 are worth doing regardless of whether the rest of the
restructuring is accepted.
