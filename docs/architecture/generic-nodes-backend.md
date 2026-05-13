# Generic Nodes Backend Redesign

This document explains what changed in the backend node architecture, why it changed, and how to add new node types safely.

## What changed

The node execution backend moved from hardcoded `if/elif` chains to a registry-based design with dedicated node modules.

Before:
- Node behavior was embedded in:
  - `apps/workers/app/activities.py`
  - `apps/api/app/main.py` (`execute_local_run`)
- Graph traversal logic was duplicated.
- Model compatibility between API and worker was not aligned.

After:
- Node behavior is now organized under:
  - `apps/workers/app/nodes/`
  - `apps/api/app/nodes/`
- Both execution paths use:
  - `BaseNodeExecutor`
  - `NodeRegistry`
  - `NodeGraphRunner`
  - `normalize_workflow_graph(...)`
- Worker and API fallback both dispatch node execution through registry lookup.
- Worker models were aligned to API payload shape (`parent`, optional `x/y`, edge `kind/slot`).

## New structure

Each backend service now has a node domain module:

- `base.py`: executor contract
- `context.py`: per-run dependencies (LLM chat, HTTP, run ids)
- `result.py`: standardized output wrapper
- `registry.py`: `componentId -> executor` dispatch
- `graph.py`: normalization + topological execution runner
- `executors/`: typed node executors grouped by domain
- `factory.py`: default registry wiring

## Runtime behavior now

1. Workflow nodes/edges are normalized with `normalize_workflow_graph(...)`.
   - nested nodes (`parent`) are excluded from execution
   - only data edges are executed
2. `NodeGraphRunner` computes order and runs nodes.
3. Each node is executed via `NodeRegistry.dispatch(...)`.
4. Existing run/node events are still emitted (`node_started`, `node_succeeded`, `node_failed`).

This keeps behavior consistent across:
- Temporal worker path
- API local fallback path

## How to add a new node type

The same pattern applies for both worker and API fallback. Today the modules are mirrored in both services, so add the node in both `apps/workers/app/nodes` and `apps/api/app/nodes` to preserve parity.

### Step 1) Create an executor

Create a class in `executors/` that extends `BaseNodeExecutor` and declares `component_ids`.

```python
from __future__ import annotations

from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult


class ApiTriggerExecutor(BaseNodeExecutor):
    component_ids = ("ApiTrigger",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        url = str(params.get("url", ""))
        method = str(params.get("method", "POST"))
        if not url:
            raise ValueError("ApiTrigger requires params.url")
        body = str(input_payload.get("value", ""))
        response_text = await context.http_request(method, url)
        return NodeExecutionResult(value=response_text, metadata={"triggerBody": body})
```

### Step 2) Register it in `factory.py`

```python
def create_default_registry() -> NodeRegistry:
    default_executor = PassthroughExecutor()
    registry = NodeRegistry(default_executor=default_executor)
    registry.register(InputExecutor())
    registry.register(PromptTemplateExecutor())
    registry.register(ChatLikeExecutor())
    registry.register(HttpRequestExecutor())
    registry.register(ApiTriggerExecutor())  # new
    registry.register(OutputExecutor())
    return registry
```

### Step 3) Add tests

Add registry and graph-runner coverage in:
- `apps/workers/tests/test_nodes_engine.py`
- `apps/api/tests/test_nodes_engine.py`

At minimum test:
- dispatch maps `componentId` to the new executor
- expected success payload
- expected failure when required params are missing

## Example: adding another LiteLLM-based node

If you need a specialized LLM node (for example `LiteLLMModeration`) you can reuse `context.llm_chat(...)`:

```python
class LiteLLMModerationExecutor(BaseNodeExecutor):
    component_ids = ("LiteLLMModeration",)

    async def execute(self, node, input_payload, context):
        params = node.get("params", {}) or {}
        content = await context.llm_chat(
            str(input_payload.get("value", "")),
            params.get("systemPrompt"),
            params.get("model"),
            float(params.get("temperature", 0.0)),
        )
        return NodeExecutionResult(value=content)
```

Then register it in `factory.py` the same way as `ApiTriggerExecutor`.

## Compatibility and safety rules

- Keep `componentId` stable for existing nodes.
- Prefer adding executors instead of editing generic dispatch code.
- Keep API and worker registry parity until a shared package is extracted.
- Preserve event contracts consumed by run stream clients.

## Quick checklist for any new node

- Add executor class in both services
- Register in both `factory.py` files
- Add or update tests in both test suites
- Run tests:
  - `apps/api`: `python -m unittest discover -s tests`
  - `apps/workers`: `python -m unittest discover -s tests`
