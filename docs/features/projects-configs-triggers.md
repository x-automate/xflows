# Projects, Configs & Triggers

How projects work end-to-end: creation on the Dashboard, the workspace tabs (Configs, Trigger),
and how project data flows to the backend.

## Dashboard

`apps/web/src/pages/Dashboard.jsx`

- Lists projects: **remote-first** (`GET /projects`), falling back to the localStorage store on
  API failure.
- **New Project** creates one via `POST /projects` (localStorage mirror too) and navigates to
  the project workspace.
- Shows cards describing the API endpoints (useful during development).

## Status Page

`apps/web/src/pages/Status.jsx`

- Polls `GET /health` every 10 s and reports "healthy" only when
  `status === "ok" && temporal === "connected"`; otherwise shows the Temporal disconnect reason.
- Useful first stop when runs behave oddly (see [Troubleshooting](../getting-started.md#troubleshooting)).

## Project Workspace

`apps/web/src/pages/ProjectLayout.jsx` renders the project header + tab navigation and provides
the project record to child routes via router outlet context. On first load it attempts
`GET /projects/:id`; if the project doesn't exist remotely yet, it is created from the local
mirror automatically.

Tabs: **Flow** (editor, default), **Configs**, **Trigger**, **Logs** — plus run routes
(`/run/new`, `/run/:runId`, `/view/:runId`) documented in [Runs](runs.md).

### Persistence behavior

Every project mutation is written to localStorage instantly and synced to the API:

| Data | Local key / module | API sync |
|---|---|---|
| Graph (`nodes`, `edges`) | `projectStore.updateProjectGraph` | 500 ms-debounced `PATCH /projects/:id` with `{graph}` |
| Configs | `projectStore.updateProject` | `PATCH /projects/:id` with `{configs}` |
| Triggers | `projectStore.saveProjectTriggers` | `POST/PATCH /projects/:id/triggers[...]` |
| Runs (mirror) | `projectStore.addProjectRun` / `updateProjectRun` | `lastRun` patched to API; remote list merged from `GET /projects/:id/runs` |

All localStorage data lives under the single key `xflows_projects` (`src/lib/projectStore.js`).
It is a cache/fallback; Postgres is the source of truth.

## Configs Tab

`apps/web/src/pages/ProjectConfigs.jsx` — "Credentials & Global Model Parameters".

- **Dynamic by design**: the required fields are derived from the nodes currently in the flow
  via `getRequiredProjectConfigs(nodes)`, which collects each node's `projectConfigs` from the
  catalog (deduplicated by `key`).
- Field types: `text`, `password`, `number`, `select`; with `required` flags, defaults, and help
  text.
- Built-in examples:
  - With a `LiteLLM` provider in the flow: `litellmApiKey` (password, required),
    `litellmBaseUrl` (required, default `http://localhost:4000`), `litellmModel` (required,
    default `gpt-4o-mini`).
  - With a `LangfuseTracer`: `langfuseHost`, `langfusePublicKey`, `langfuseSecretKey`.
  - With a `LangsmithTracer`: `langsmithEndpoint`, `langsmithProject`, `langsmithApiKey`.
- Saves to localStorage + `PATCH /projects/:id` (`{configs}`), showing saved/error feedback.

### How configs reach runs

Config values that are provider **secrets** never travel in configs (fix XF-01, Wave 4):

1. The Configs tab saves them to `project.configs`; on save, the API's
   `PATCH /projects/:id` handler **splits secret-shaped keys** (`*ApiKey*`, `*Secret*`,
   `*Token*`, `*Password*`, `*Credential*`) out of `configs` into the `project_secrets`
   table — the API responses (`GET /projects`) therefore never carry key material.
2. Secret *names* are set explicitly via `PUT /projects/:id/secrets` (`{name, value}`) and
   listed (names only) via `GET /projects/:id/secrets`.
3. A run's `metadata.runtimeConfig` may reference a secret by name using a `<key>Ref`
   entry (e.g. `litellmApiKeyRef: "litellm-key"`).
4. At execution time the worker resolves the ref via the internal endpoint
   `GET /internal/runs/{runId}/secrets/{name}` (internal-token guarded), caches the value in
   memory for the run only, and injects the concrete key into that node's scoped config.
5. Config scoping (fix XF-06): every node receives a runtime config stripped of
   secret-shaped keys unless its component genuinely needs them
   (`SECRET_BEARING_COMPONENTS`: LLM, LiteLLM, ChatOllama, AgentLoop, HttpRequest, ApiCaller).

Per-session API-key entry in the test panel was removed intentionally: provider settings are
managed in one place and used consistently by local and worker execution.

## Trigger Tab

`apps/web/src/pages/ProjectTriggers.jsx` — a table of **time-based** triggers:

| Column | Meaning |
|---|---|
| Enabled | Checkbox toggling the trigger |
| Queue | Named queue (stored in trigger config) |
| Time | Scheduled time |
| Timezone | Local or UTC |

Backend model (`TriggerRecord`): `{id: trg_<10hex>, type: "time" | "webhook" | "event",
enabled, config: {queue, time, timezone}, projectId, ...}`. The UI currently manages `time`
triggers; `webhook` and `event` types exist in the API contract for future schedulers.

On save the UI lists remote triggers, then PATCHes existing ids / POSTs new ones
(`{type: "time", enabled, config}`), then hydrates back from the API response; localStorage is
the fallback.

## Trigger Execution (Wave 4, XU-8)

Trigger rows are now executed, not just persisted:

- **Webhook triggers**: creating a `webhook` trigger generates a registration secret
  (`config.signatureSecret`). `POST /webhooks/{triggerId}` verifies the HMAC-SHA256 signature
  of the raw body (`X-Webhook-Signature: sha256=<hex>`), derives an idempotency key from
  `X-Delivery-Id` (or the body hash), and creates exactly one run — duplicate deliveries
  return the same run id. Requires `config.workflowId`.
- **Time triggers**: a lightweight scheduler tick in the API process (interval
  `TRIGGER_SCHEDULER_INTERVAL_S`, default 30 s) fires each enabled `time` trigger once per
  interval slot: the slot maps to an idempotency key (`trigger:{triggerId}:{slot}`), so
  duplicate ticks are deduped by the idempotency index and a slot fires a run exactly once.
  `event` triggers remain deferred to P2.
- **Deletion (fix XF-05)**: `DELETE /projects/:id`, `DELETE /workflows/:id` (refused with 409
  while runs exist — archive instead; run history is retained), and
  `DELETE /projects/:id/triggers/:triggerId`. Workflows can be `published`/`archived` via
  `POST /workflows/:id/publish|archive`; archived workflows refuse new runs (409).

## Users

The API has user records (`POST /users`, `GET /users`, `GET /users/{id}`) with
`authProvider` (default `local`). Projects carry an optional `ownerUserId` FK. There is no
login UI yet — see the [API reference](../reference/api-reference.md#users) and
[architecture security notes](../architecture/overview.md#security-posture-current).
