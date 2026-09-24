# Node Execution Engine

How a workflow graph becomes executed node-by-node. The same engine powers both execution paths:
the Temporal worker (`apps/workers/app/nodes/`) and the API's local fallback
(`apps/api/app/nodes/`) — deliberately mirrored modules with identical behavior (see
[design rationale](../architecture/generic-nodes-backend.md)).

## Pipeline

```
raw graph (workflow record: nodes[] + edges[])
  └─ normalize_workflow_graph(nodes, edges)
  └─ topo_sort(nodes, edges)                    # Kahn's algorithm; cycle ⇒ ValueError
  └─ NodeGraphRunner(nodes, edges, user_input)
       └─ run(execute) → (outputs, order)       # sequential, topological
  └─ resolve_output_node_id(order)              # run output selection
```

### Graph normalization

`normalize_workflow_graph` (`nodes/graph.py`):

- Groups nodes by `parent`; for each top-level node, merges its **first child** (provider child)
  into it:
  - merged `componentId` = child's `componentId`
  - merged `params` = `{**parent.params, **child.params}` (child wins)
  - merged node gains `providerComponentId = child.componentId`
- Nodes with a `parent` are removed from the executable graph (containers run their children by
  promotion, not as separate steps).
- Edges are filtered to `kind == "data"` (missing kind defaults to `"data"`); `config` edges are
  designer metadata only. Edges referencing removed/unknown node ids are dropped.

Example (tested): `LLM` container with nested `LiteLLM` child → single node with
`componentId="LiteLLM"`, merged `model` param, `providerComponentId="LiteLLM"`.

### Topological execution

- Kahn's algorithm over data edges; a cycle raises `ValueError("Workflow graph contains a cycle")`
  → run fails.
- Input per node: the output payload of its incoming data edge's source; **one incoming edge per
  node survives (last edge wins)** — no fan-in merging today.
- Root nodes (no incoming data edge) receive `{"value": user_input}` — the run's input text.
- Execution is strictly sequential in topological order.

### Output selection

`resolve_output_node_id(order)`: the first node with `componentId == "Output"`, else the last
node in topo order. The run's `output` is that node's `value`.

## Core Building Blocks

| Module | What it provides |
|---|---|
| `base.py` | `BaseNodeExecutor` — declares `component_ids: tuple[str, ...]`; `async execute(node, input_payload, context) -> NodeExecutionResult` |
| `result.py` | `NodeExecutionResult(value, metadata)`; `to_payload()` → `{"value": value, **metadata}` |
| `context.py` | `NodeExecutionContext(run_id, trace_id, user_input, llm_chat, http_request, runtime_config)` — injected dependencies; identical signatures in both services (worker's `llm_chat` returns a dict `{model, provider, content, usage}`) |
| `registry.py` | `NodeRegistry(default_executor)` — maps each `component_id` → executor; `dispatch(node, input_payload, context)` falls back to the default (passthrough) executor for unknown `componentId`s |
| `graph.py` | `normalize_workflow_graph`, `topo_sort`, `NodeGraphRunner` |
| `factory.py` | `create_default_registry()` — wires the built-in executors |

## Built-in Executors

| Executor class | componentId(s) | Behavior |
|---|---|---|
| `InputExecutor` | `Input` | value = the run's user input |
| `PromptTemplateExecutor` | `PromptTemplate` | renders `params.template` with `{input}` replaced by the upstream value; metadata `{"system": params.system \| default}` consumed by chat nodes |
| `ChatLikeExecutor` | `LLM`, `OpenAIChat`, `AnthropicChat`, `ReActAgent` | calls `context.llm_chat(prompt, system (if str), model_hint, temperature)`; metadata `{provider, model, usage}` (worker) / `{model}` (API fallback) |
| `LiteLlmExecutor` | `LiteLLM` | same chat call; metadata adds `provider: "litellm"`, `apiBase` (`params.apiBase` \| `runtimeConfig.litellmBaseUrl`) |
| `HttpRequestExecutor` | `HttpRequest` | `params.method` (default GET), `params.url` required — `ValueError("HttpRequest requires a URL")`; returns response text |
| `ApiCallerExecutor` | `ApiCaller`, `ApiCall` | same; method upper-cased; metadata `{"status": "ok", "method", "url"}` |
| `WebhookTriggerExecutor` | `Webhook`, `WebhookTrigger` | declarative passthrough; metadata `{"trigger": "webhook", "webhook": {path, method, secretHeader}}` |
| `LangfuseTracerExecutor` | `LangfuseTracer` | passthrough; metadata `{"traceProvider": "langfuse", "traceConfig": {host, publicKey, tags}}` |
| `LangsmithTracerExecutor` | `LangsmithTracer` | passthrough; metadata `{"traceProvider": "langsmith", "traceConfig": {endpoint, project, tags}}` |
| `OutputExecutor` | `Output` | passthrough — marks the terminal output |
| `PassthroughExecutor` | (default) | unknown componentIds pass the value through |

Note: tracer and webhook nodes do not perform external calls at this layer — they annotate run
metadata. Actual Langfuse spans are opened by the worker's `LangfuseTracer`
(`apps/workers/app/tracing.py`) around every activity when `LANGFUSE_*` env keys are set.

## Model Resolution

For chat-family executors (`ChatLikeExecutor`, `LiteLlmExecutor`):

1. **model**: `params.model` → `runtimeConfig["litellmModel"]` → server default
   (`LITELLM_MODEL_ALIAS`, default `gpt-4o-mini`).
2. **temperature**: `params.temperature` → `runtimeConfig["temperature"]` → `0.2`.
3. **system prompt**: upstream `PromptTemplate` metadata `system` if present (string).
4. **API key / base URL**: `runtimeConfig["litellmApiKey"]` → settings
   (`LITELLM_API_KEY` → `LITELLM_MASTER_KEY`); base URL: LiteLLM node `params.apiBase` (when
   non-empty) → `runtimeConfig["litellmBaseUrl"]` → `LITELLM_BASE_URL`. A trailing `/v1` is
   stripped, and an explicit node `apiBase` bypasses `xwsGatewayBaseUrl` routing. A LiteLLM node
   still holding the old auto-persisted catalog defaults (`apiBase: http://litellm:4000`,
   `model: openai/gpt-4o-mini`) defers to the project's `litellmBaseUrl` / `litellmModel`.

`runtimeConfig` is resolved by the API at run creation: the project's stored configs, overlaid by
the caller's inline `metadata.runtimeConfig`, plus a `<key>Ref` for every stored project secret
not supplied inline (resolved by the worker at execution time). Trigger-fired runs get the same
project config. Inline secret values are redacted (`***`) in the persisted run record.

## Model Routing (Fallback Chain)

`LiteLLMRouter` (`apps/workers/app/provider_router.py`) — used only on the worker path (the API
fallback calls LiteLLM directly with a single candidate model):

- POSTs `{model, messages, temperature}` to `{base}/v1/chat/completions` (httpx, 60 s timeout).
- Candidate chain: the node's model hint, then `runtimeConfig["litellmModel"]`, then the
  default fallback chain (minus duplicates):
  1. `openai/gpt-4o`
  2. `vllm/meta-llama/Llama-3.1-8B-Instruct`
  3. `ollama/llama3.1:8b`
- Each candidate is tried in order on any failure (HTTP ≥400 or exception); the first success
  returns `{model, provider, content, usage}` (provider looked up from a static
  `CAPABILITY_REGISTRY`). All failing ⇒ `RuntimeError("LiteLLM routing failed: …")`.
- Model names are sent **verbatim** — no prefix trimming (see root README).

`CAPABILITY_REGISTRY` (static capability map):

| Model | Provider | Tools | Context |
|---|---|---|---|
| `openai/gpt-4o` | OpenAI | yes | 128k |
| `openai/gpt-4o-mini` | OpenAI | yes | 128k |
| `ollama/llama3.1:8b` | Ollama | no | 8192 |
| `vllm/meta-llama/Llama-3.1-8B-Instruct` | vLLM | yes | 8192 |

## Temporal Execution Model

`apps/workers/app/workflows.py` — `XFlowsWorkflow` (`@workflow.defn(name="XFlowsWorkflow.run")`):

1. Validate the definition payload into `WorkflowDefinition` (Pydantic).
2. Normalize + topo-sort exactly as above.
3. For each node, call activity **`xflows.execute_node`** with
   `[node, input_payload, run_id, trace_id, runtime_config]`:
   - `schedule_to_close_timeout = 120 s`
   - `RetryPolicy`: initial 1 s, max interval 20 s, max attempts 3
4. Call activity **`xflows.complete_run`** with `[run_id, trace_id, "succeeded"|"failed", payload]`
   (30 s schedule-to-close); on failure the error is re-raised after emitting `run_failed`.
5. Returns `{runId, traceId, status, output}`.

`xflows.execute_node` (`apps/workers/app/activities.py`) additionally:

- wraps execution in the `xflows_node_execution_seconds` histogram and
  `xflows_node_executions_total{component,status}` counter,
- opens a Langfuse span (`node:{componentId}`) around execution with the input payload,
- emits `node_started` / `node_succeeded` / `node_failed` to the API.

Replay determinism: the workflow imports `WorkflowDefinition` and the node engine under
`workflow.unsafe.imports_passed_through()`.

## Local Fallback Path

`execute_local_run` (`apps/api/app/main.py`): background task that sets the run `running`,
normalizes the graph, wires `llm_chat` → direct LiteLLM HTTP call (single candidate model,
60 s timeout) and `http_request` → httpx (30 s), then runs the same registry dispatch, emitting
the same events. Differences vs worker path: single-candidate model resolution (no fallback
chain) and no Langfuse spans — otherwise identical semantics.

## Adding a Node Type

Step-by-step guide with code: [Generic nodes backend](../architecture/generic-nodes-backend.md#how-to-add-a-new-node-type)
— summary: create the executor in both services, register in both `factory.py` files, add tests
to both suites (`python -m unittest discover -s tests` in each app), and add the catalog entry
(see [node catalog](../features/node-catalog.md#extending-the-catalog)).
