# Node Catalog

The catalog is JSON-driven: a single shared file,
`packages/xflows-catalog/node-registry.json`, defines every component's identity,
visual metadata, params, config slots, required project configs, and implementation
status. All editor surfaces (canvas, palette, steps pane, properties panel, param modal)
read from it via `catalog/catalog-meta.js`.

## Catalog File Structure

```jsonc
{
  "version": 1,
  "categoryColors": { "I/O": { "fg": "...", "bg": "...", "dot": "..." }, /* 14 categories */ },
  "components": [
    {
      "id": "LiteLLM",           // componentId — the execution identity
      "name": "LiteLLM",         // display name
      "category": "LLM-Provider",
      "kind": "provider",        // input|output|transform|container|provider|tool|aux|router|llm
      "icon": "litellm",         // key into the inline SVG icon map (XFLOWS_ICONS)
      "desc": "Route model calls via LiteLLM provider gateway.",
      "status": "working",       // working|partial|planned
      "statusNote": "…",         // optional: why partial/planned and which wave fixes it
      "accepts": ["LLM-Provider"],          // containers only: categories it may nest
      "configs": [ { "name": "tracer", "label": "tracer", "accepts": ["Observability"] } ],
      "params": [ { "name": "model", "type": "text", "default": "openai/gpt-4o-mini" } ],
      "projectConfigs": [ { "key": "litellmApiKey", "label": "...", "type": "password",
                            "required": true, "default": "...", "help": "..." } ],
      "backendActivity": "xflows.execute_node"
    }
    // 39 components total
  ]
}
```

Field semantics:

| Field | Meaning |
|---|---|
| `id` | The `componentId` stored on workflow nodes; must match a backend executor (or fall through to passthrough) |
| `kind` | Rendering/behavior hint: `input`, `output`, `transform`, `container`, `provider`, `tool`, `aux`, `router`, `llm` |
| `status` | `working` — executor fully matches declared params; `partial` — runs but does not support all declared params; `planned` — inert placeholder |
| `statusNote` | Optional: why the node is `partial`/`planned` and which upgrade wave fixes it (XU-x) |
| `accepts` | Container only: categories that may be nested inside |
| `configs` | Container config slots (bottom ports) for attaching aux nodes via config edges |
| `params` | Parameter schema rendered by the properties panel/param modal (types: `text`, `textarea`, `number` + `step`, `select` + `options`, `bool`) |
| `projectConfigs` | Fields surfaced on the project Configs tab when this component is present in the flow |
| `backendActivity` | The Temporal activity that will execute this component (currently `xflows.execute_node` for all); unknown values are reported by `getUnsupportedComponents()` and block runs |

Status enforcement (XU-10):

- `planned` components are **visible but unplaceable** in the component panel (no drag,
  no double-click add) and fail authoring validation if present on the canvas.
- `partial` components are placeable and runnable; their `statusNote` is shown in the
  properties panel so users know the exact gaps.

Adapter modules:

- `catalog/catalog-meta.js` — `XFLOWS_CATALOG`, `CATEGORY_COLORS`, `XFLOWS_ICONS` (inline SVGs),
  `STATUS_META` (status chip styling), `isPlaceable(component)`,
  `getComponentMeta(id)` (O(1) lookup), `getRequiredProjectConfigs(nodes)`.
- `catalog/execution-map.js` — `BACKEND_EXECUTION_MAP` and `getUnsupportedComponents(nodes)`
  (unknown ids **and** `planned` components are unsupported).

## Component Status

| Status | Count | Components |
|---|---|---|
| working | 23 | Input, Output, PromptTemplate, LLM, OpenAIChat, AnthropicChat, LiteLLM, ApiCaller, IfElse, Switch, Wait, Approval, AgentLoop, SchemaValidate, Codegen, SubWorkflow, XWSS3, XWSLambdaInvoke, XWSIAMEvaluate, XWSRelayNotify, XWSGatewayLLM, WebSearch, VectorStore |
| partial | 2 | HttpRequest (headers/body/auth ignored, XF-09), LangfuseTracer (node params not applied; run-level tracing active) |
| planned | 14 | Webhook (XU-8), ReActAgent (XU-3), CodeExec, Summarizer, JsonParser, RegexExtract, Markdown, Tracer, LangsmithTracer (Wave 6), Guardrail, LoopOverItems (Wave 6), XWSDmsIntrospect, XWSApigwRegister, XWSAudit (XWS Wave 4+) |

The five working XWS tools (Waves 3 + 5) execute via the SigV4-signed XWS transport with
per-run AssumeRole credentials; the three remaining planned XWS tools are inert placeholders
pending XWS-side capabilities (DMS introspection, API GW registration, audit trail).
Wave 4 added the working `Approval` HITL gate (XU-5) — see the Control section below.
Wave 5 added the working `SchemaValidate`, `Codegen`, and `SubWorkflow` pipeline nodes
(XU-3/XU-6) and flipped `XWSGatewayLLM` to working (structured LLM outputs via the gateway).

Wave 1 control-flow semantics (XU-6):

- Edges may carry `when` predicates — a safe expression grammar (`==`, `!=`, `>`, `>=`,
  `<`, `<=`, `&&`, `||`, `!`, parentheses, string/number literals, dotted paths,
  `contains()`, `startsWith()`, `endsWith()`) evaluated against the upstream node's output
  payload. An edge only delivers when its predicate passes.
- Outgoing `error` edges catch node failures (after activity retries): the target receives
  `{value: "", error: {message, nodeId, componentId}}`. A node without an error edge fails
  the run; `onError: "continue"` passes the upstream payload downstream instead.
- Fan-in to one node from multiple upstream nodes merges deterministically: single input
  passes through untouched; multiple inputs produce `{value: <first edge>, branches: {edgeId: payload}, items: [...]}`.
- Nodes execute level-by-level: independent nodes in the same level run concurrently.
- `Wait` pauses via a durable Temporal timer (`workflow.sleep`), not a blocked worker.
- `Approval` parks via durable Temporal signals (`approve`/`reject`/`request_changes`) with a
  timeout timer (`signalTimeoutS`, default 72h); the node value is the decision payload, so
  downstream `when` predicates route on `value.decision` (e.g. `value.decision == 'approved'`).
  Signals arrive via `POST /runs/{id}/approve|reject|request-changes`.

## Categories (14)

| Category | Color dot | Components |
|---|---|---|
| I/O | slate | Input, Output |
| Prompt | violet | PromptTemplate |
| LLM | teal | LLM (container) |
| LLM-Provider | teal | OpenAIChat, AnthropicChat, LiteLLM |
| Tool | orange | HttpRequest, ApiCaller, WebSearch, CodeExec |
| Memory | blue | VectorStore, Summarizer |
| Router | yellow | IfElse, Switch |
| Control | indigo | Wait, Approval, LoopOverItems |
| Parser | cyan | JsonParser, RegexExtract |
| Agent | rose | ReActAgent, AgentLoop |
| Format | slate | Markdown |
| Observability | orange | Tracer, LangfuseTracer, LangsmithTracer, Guardrail |
| Trigger | blue | Webhook |
| XWS | purple | XWSS3, XWSLambdaInvoke, XWSIAMEvaluate, XWSRelayNotify, XWSGatewayLLM, XWSDmsIntrospect, XWSApigwRegister, XWSAudit |

## Component Reference

The tables below document every component exactly as declared in `node-registry.json`.
"Executed by" refers to the backend executor (see
[node execution reference](../reference/node-execution.md#built-in-executors)).

### I/O

| id | Params | Executed by | Notes |
|---|---|---|---|
| `Input` | — | `InputExecutor` | Entry point; executor returns the run's user input |
| `Output` | — | `OutputExecutor` | Marks the final output node; run output = its value |

### Prompt

| id | Params | Executed by |
|---|---|---|
| `PromptTemplate` | `template` (textarea, default `Answer concisely:\n\n{input}`), `system` (textarea, default `You are a helpful assistant.`) | `PromptTemplateExecutor` — replaces `{input}` in the template; passes `system` downstream as metadata |

### LLM & Providers

`LLM` is the only container. It exposes three config slots: `tracer` (accepts Observability),
`memory` (accepts Memory), `tools` (accepts Tool), and accepts exactly one `LLM-Provider` child.

| id | Params | Notes |
|---|---|---|
| `OpenAIChat` | `model` (select: gpt-4o-mini / gpt-4o / gpt-4-turbo, default gpt-4o-mini), `temperature` (number, 0.7, step 0.1), `max_tokens` (number, 512) | Executed by `ChatLikeExecutor` |
| `AnthropicChat` | `model` (select: claude-haiku-4-5 / claude-sonnet-4-5 / claude-opus-4), `temperature` (0.7), `max_tokens` (1024) | Executed by `ChatLikeExecutor` |
| `LiteLLM` | `model` (text, default `openai/gpt-4o-mini`), `temperature` (0.2), `apiBase` (text, default empty = use the project's `litellmBaseUrl`) | Executed by `LiteLlmExecutor`; carries 3 required `projectConfigs` (below) |

`LLM` container itself: no params; at run time it is replaced by its promoted provider child.

Model resolution for chat executors: `params.model` → `runtimeConfig.litellmModel` → server
default; temperature: `params.temperature` → `runtimeConfig.temperature` → `0.2`.

Structured outputs (XU-4, Wave 2): every LLM provider accepts `outputSchema` (JSON Schema),
`strictSchema` (default true) and `maxRepairAttempts` (default 1). When `outputSchema` is set,
the request carries OpenAI-compatible `response_format.json_schema`; the response is parsed
(code fences and prose tolerated) and validated (full validator when `jsonschema` is installed
in the worker, else a builtin type/required/enum/items subset). Invalid output triggers a repair
retry whose prompt embeds the schema, the raw output and the validation errors; a still-invalid
output fails the node loudly in strict mode, or is returned unvalidated with
`schemaValidated: false` + `schemaErrors` when strict is off. `max_tokens` is sent as
`max_tokens` in the request payload (XF-11).

LLM routing (Wave 2): the fallback chain is configurable via worker setting
`LITELLM_FALLBACK_MODELS` (comma-separated, default `openai/gpt-4o,vllm/…,ollama/…`) and per-run
`runtimeConfig.litellmFallbackModels`. When `runtimeConfig.xwsGatewayBaseUrl` is set, calls route
to the XWS Model Gateway `POST /v1/gateway/complete` instead (provider `xws-gateway`, optional
`gatewayStage` in the payload, `xwsGatewayApiKey` for auth; Wave 3 adds SigV4-signed transport
with per-run credentials — see [XWS tools](#xws) below).
Per-node usage is normalized to `{input, output, total, costUsd?}` and aggregated at the run
level into `metadata.usage = {inputTokens, outputTokens, totalTokens, costEstimateUsd, nodes}`
(XF-11; costs are estimates from a built-in price table, unknown models have no cost).

### Tool

| id | Params | Executed by |
|---|---|---|
| `HttpRequest` | `method` (select GET/POST, default GET), `url` (text), `body_uses_input` (bool, true) | `HttpRequestExecutor` — URL required, else the node fails |
| `ApiCaller` | `method` (select GET/POST/PUT/PATCH/DELETE, default GET), `url` (text) | `ApiCallerExecutor` (alias `ApiCall`) — URL required |
| `WebSearch` | `top_k` (number, 3) | DuckDuckGo Lite search via HTTP; query from node params/upstream input, passthrough fallback on failure |
| `CodeExec` | `code` (textarea, default `return input.toUpperCase();`) | Passthrough today (sandbox pending) |

### XWS

XWS (X Workload Service) tool nodes call the APIGen backbone over **SigV4-signed HTTPS**
(docs 05 §4/§7, 06 XU-2, 08 A8/A11/G-5). All four working executors share one transport:

- **Signing** — AWS SigV4 with service `xws`; canonical URI/query are built from the decoded
  path (single-encoding, idempotent) and query sorted by key with blank values kept;
  headers `x-amz-date`, `x-amz-content-sha256`, `x-xws-project` (project id) and
  `x-amz-security-token` (when session creds are present) are signed.
- **Per-run credentials** — the worker's embedded `CredentialVendor` vends STS
  credentials lazily per `(run_id, toolClass)` via iam-svc (backbone fixes A11/G-5: no
  static service keys on tool requests); the least-privilege role per toolClass comes
  from the `xws_role_arns` map (`XWS_ROLE_ARNS`, `toolClass=arn,...`), and credentials
  are cached per run + toolClass and refreshed 120s before expiry.
- **Retries** — retryable requests use exponential backoff (5 attempts, 0.2s base delay,
  per docs 05 §4); the client bounds each attempt with a 30s HTTP timeout.
- **Errors** — typed `XWSError` hierarchy: `XWSSignatureError`, `XWSCredentialError`,
  `XWSAllowlistError`, `XWSRequestError` (with `status_code`/`body`).

The engine executors dispatch through the `context.xws_client` seam (`packages/xflows-engine/
xflows_engine/executors/xws_tools.py`); the real client is built per run in the worker
(`apps/workers/app/activities.py`). No-op / simulated mode is used when XWS env settings are
absent. `AgentLoop` reuses the same route surface for model-initiated tool calls.

| id | Params | Route | Executed by |
|---|---|---|---|
| `XWSS3` | `operation` (select put/get/list_versions, default put), `key` (text), `bucket` (text, `apigen-artifacts`), `toolClass` (text, `s3`) | `PUT/GET /s3/{bucket}/{key}` (`list_versions` sends `?versions=true`) | `XWSS3Executor` |
| `XWSLambdaInvoke` | `functionName` (text), `bundleHash` (text), `toolClass` (text, `lambda`) | `POST /lambda/invoke/{functionName}` with `{payload, bundleHash}` + `Idempotency-Key: bundle-{bundleHash}` | `XWSLambdaInvokeExecutor` — functionName+bundleHash required |
| `XWSIAMEvaluate` | `principal` (text), `action` (text), `resource` (text), `toolClass` (text, `iam`) | `POST /iam/evaluate` with `{principal, action, resource, context}` | `XWSIAMEvaluateExecutor` — all three args required |
| `XWSRelayNotify` | `message` (textarea), `deepLink` (text), `channel` (text, default `console`), `toolClass` (text, `relay`) | `POST /relay/notify` with `{message, deepLink, channel, card}` | `XWSRelayNotifyExecutor` — message required |
| `XWSGatewayLLM` | `prompt` (textarea), `system` (textarea), `model` (text), `temperature` (number, 0.7), `maxTokens` (number, 1024), `outputSchema` (text), `toolClass` (text, `llm`) | `POST /v1/gateway/complete` with `{prompt, system, model, temperature, maxTokens, response_format}` | `XWSGatewayLLMExecutor` — working (Wave 5): strict json_schema response format when `outputSchema` is set, re-validated locally |
| `XWSDmsIntrospect` | `toolClass` (text, `dms-ro`), `readOnly` (bool, true) | — | Planned: DMS schema introspection (read-only) |
| `XWSApigwRegister` | `toolClass` (text, `apigw`) | — | Planned: API Gateway stage registration |
| `XWSAudit` | `toolClass` (text, `audit`) | — | Planned: audit-trail emission |

The three remaining planned XWS nodes are inert placeholders pending XWS-side capabilities
(DMS introspection, API GW registration, audit trail); they carry `toolClass` params so
per-role credential wiring is already declared.

### Trigger

| id | Params | Executed by |
|---|---|---|
| `Webhook` | `path` (text, `/webhook`), `method` (select POST/PUT, default POST), `secretHeader` (text, `x-webhook-secret`) | `WebhookTriggerExecutor` — declarative passthrough; attaches trigger metadata |

### Memory

| id | Params | Notes |
|---|---|---|
| `VectorStore` | `collection` (text, `docs`), `top_k` (number, 3), `query` (text, "") | Aux node; attach to the LLM `memory` slot. Passes input through, echoing `collection`/`top_k`/`query` in metadata |
| `Summarizer` | `max_chars` (number, 200) | Transform (passthrough semantics today) |

### Control

| id | Params | Executed by |
|---|---|---|
| `Wait` | `seconds` (number, 1) | Durable Temporal timer in the workflow (`workflow.sleep`), not the generic activity |
| `Approval` | `summary` (textarea), `signalTimeoutS` (number, 259200), `notifyChannel` (text, `console`), `notifyDeepLink` (text) | `ApprovalExecutor` + Temporal signal parking (XU-5) — see below |
| `SchemaValidate` | `schema` (textarea, inline JSON Schema), `outputSchema` (text, named schema) | `SchemaValidateExecutor` — deterministic, no LLM; raises on any violation |
| `Codegen` | `template` (text, `fastapi-arc1@1.4.0`) | `CodegenExecutor` — deterministic FastAPI stub generation; returns `{codeBundleRef, files, hash, template}` |
| `SubWorkflow` | `workflowId` (text) / `workflow` (text), `runtimeConfig` (textarea, JSON object) | Workers layer `SubWorkflowExecutor` seam — child Temporal workflow; see below |
| `LoopOverItems` | `batchSize` (number, 1) | Planned (Wave 6 items work) |

`Approval` semantics (Wave 4, XU-5): the engine executor builds an approval request
(`{runId, nodeId, summary, evidence, notify, signalTimeoutS}`) and resolves it through the
`context.await_approval` seam — implemented in the workers layer as a Temporal signal wait
(`approve`/`reject`/`request_changes` handlers) with a timeout timer that yields the
fail-closed `timeout` decision (04 §5). Before parking, the `xflows.prepare_approval`
activity persists `run_awaiting_review` to `run_events` and notifies reviewers via
`XWSRelayNotify` (card + deep link). The decision is recorded as `signal_received` by
`xflows.record_approval`; the node value is the decision payload
(`{"decision": "approved|rejected|request_changes|timeout", "reviewer", "comment", "evidence"}`)
so downstream `when` predicates route on `value.decision`
(the node payload is `{value: decision, approval: {...}}` — e.g. `value.decision == 'approved'`).
Decision aliases
(`approve`→`approved`, `reject`→`rejected`, `escalate`→`timeout`) normalize in both the
engine and the workers gate; unknown decisions fail closed to `timeout`.

`SubWorkflow` semantics (Wave 5, XU-3/XU-6): the workers layer dispatches child Temporal
workflows with per-node unique ids (`{runId}:{nodeId}`, or `{runId}:validate-N` per repair
round). Three dispatch shapes, resolved in order:

1. **Inline definition** — `params.workflowDefinition` (dict) starts `XFlowsWorkflow.run`
   with the embedded graph; non-string child input is JSON-encoded.
2. **APIGen registry** — `workflowId` of `apigen.generate` / `apigen.validate` /
   `apigen.deploy` starts the dedicated `ApiGen{Generate,Validate,Deploy}Workflow.run`
   child directly (dict input passed as-is; otherwise wrapped as `{"value": ...}`).
3. **Stored workflow** — any other id fetches the definition at run time via the
   `xflows.load_workflow` activity (API `GET /internal/workflows/{id}`, internal-token
   guarded) and starts `XFlowsWorkflow.run`; `params.runtimeConfig` is merged over the
   parent runtime config. A child that does not succeed fails the node.

### APIGen pipeline (Wave 5, docs 04 §2)

The pipeline ships as three durable Temporal workflows in `apps/workers/app/workflows.py`
rather than a stored graph; the API dispatches to them when a stored workflow's metadata
carries `{"apigen": "generate|validate|deploy"}` (same ids as the SubWorkflow registry):

- `ApiGenGenerateWorkflow.run` — classify (AgentLoop, schema-validated) → clarify loop
  (≤5 rounds, agent) → spec loop (≤5 rounds of AgentLoop + SchemaValidate + lint; invalid
  rounds retry with lint feedback) → Codegen → validate child workflow with ≤3 repair
  rounds (deterministic re-codegen on validation failure) → `review` Approval gate →
  IAM policy check → deploy child workflow → manifest. Terminals: `succeeded`,
  `rejected` (classification, review, or policy), `needs_input` (clarify exhausted),
  `failed` (spec lint exhausted, repair exhausted, deploy failure).
- `ApiGenValidateWorkflow.run` — invokes the `apigen-bundle-validator` Lambda; requires
  `bundleHash` (or `bundle.hash`).
- `ApiGenDeployWorkflow.run` — invokes the `apigen-deployer` Lambda with secret bindings
  (`*Ref` runtime entries map to `secretBindings`); builds the deploy manifest
  (`specHash`, `sandbox:/live:` aliases or Lambda-provided overrides, `deployedAt`).


### Router

| id | Params | Notes |
|---|---|---|
| `IfElse` | `contains` (text), `mode` (select warn/fail, default warn) | Contains-check router |

### Parser

| id | Params |
|---|---|
| `JsonParser` | `extract_path` (text, "") |
| `RegexExtract` | `pattern` (text, `\d+`), `flags` (text, `i`) |

### Agent

| id | Params | Notes |
|---|---|---|
| `ReActAgent` | `max_steps` (number, 3), `tools` (text, `search,calculator`) | Planned (XU-3); superseded functionally by `AgentLoop` |
| `AgentLoop` | `maxIterations` (number, 5), `tokenCap` (number, 20000), `timeoutS` (number, 60), `allowlist` (text, `s3,lambda,iam,relay`) | Executed by `AgentLoopExecutor` — bounded tool-calling loop over XWS tools |

`AgentLoop` semantics (Wave 3, XU-3): the node drives a bounded reasoning/action loop against
the connected LLM container. Each turn sends the accumulated message history (JSON-encoded
prompt string) to `llm_chat`; the model must answer with a JSON envelope — either
`{"action": "tool", "tool": "<XWSS3|XWSLambdaInvoke|XWSIAMEvaluate|XWSRelayNotify>", "toolClass": "<class>", "args": {...}}`
(args are filtered to the tool's known arg keys) or `{"action": "final", "output": "<answer>"}`.
Tool calls are dispatched through the engine's `context.xws_client` seam (allowlist is
comma-separated **toolClasses**; a call to a class outside the allowlist or an unknown tool
yields an `{"error": ...}` observation appended to the transcript, not a node failure). The
loop ends with `stopReason` `final`, `timeout` (after `timeoutS`), `token_cap` (cumulative
usage tokens ≥ `tokenCap`), `invalid_envelope`, `invalid_action`, or `max_iterations`
(`maxIterations` tool turns consumed without a final answer) —
in every non-final case the node returns the error + transcript JSON as its value. The full
transcript, iterations, tokensUsed and stopReason are always attached to result metadata as
`agentLoop`, so the workers layer can persist them to `run_events`.

### Format

| id | Params |
|---|---|
| `Markdown` | `wrap` (select as-is/codeblock/quote/bullets, default as-is) |

### Observability (aux — connect via config edges to the LLM `tracer` slot)

| id | Params | projectConfigs | Executed by |
|---|---|---|---|
| `Tracer` | `level` (select info/debug/verbose), `destination` (select console/trace-panel/both) | — | Passthrough |
| `LangfuseTracer` | `host` (default https://cloud.langfuse.com), `publicKey`, `tags` (default `prod,web`) | `langfuseHost`, `langfusePublicKey`, `langfuseSecretKey` — all required | `LangfuseTracerExecutor` — passthrough + trace metadata |
| `LangsmithTracer` | `endpoint` (default https://api.smith.langchain.com), `project` (default `xflows`), `tags` (`prod,web`) | `langsmithEndpoint`, `langsmithProject`, `langsmithApiKey` — all required | `LangsmithTracerExecutor` — passthrough + trace metadata |
| `Guardrail` | `forbidden` (text, `password,secret`) | — | Passthrough |

Note: actual Langfuse span creation happens in the worker (`apps/workers/app/tracing.py`) when
the `LANGFUSE_*` environment keys are configured; the node contributes config metadata to the
run (see [Observability](../observability.md#tracing-langfuse)).

## Extending the Catalog

Adding a new end-to-end node touches three places:

1. **Catalog entry** in `packages/xflows-catalog/node-registry.json` (category, params,
   optional `projectConfigs`, optional `status`/`statusNote`,
   `backendActivity: "xflows.execute_node"`).
2. **Backend executor** class in `packages/xflows-engine/xflows_engine/executors/` and
   registration in `xflows_engine/factory.py` (`create_default_registry`).
3. **Tests** in `packages/xflows-engine/tests/test_engine.py` (both apps share the engine;
   the app-level smoke tests in `apps/api/tests` and `apps/workers/tests` only verify that
   the shared package imports and dispatches from each app's environment).

Full walkthrough with code: [Generic nodes backend](../architecture/generic-nodes-backend.md#how-to-add-a-new-node-type).
