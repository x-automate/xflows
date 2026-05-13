# Observability and Evaluation

## Trace Model (Langfuse)

- **Trace**: one trace per workflow run (`traceId`)
- **Generation/Span**: one span per node execution
- **Metadata fields**:
  - `runId`
  - `workflowId`
  - `workflowVersion`
  - `nodeId`
  - `componentId`
  - `provider`
  - `model`

## Core Metrics

- API:
  - `xflows_runs_created_total`
  - `xflows_runs_completed_total{status=...}`
  - `xflows_run_create_latency_seconds`
- Worker:
  - `xflows_node_executions_total{component,status}`
  - `xflows_node_execution_seconds{component}`

## Suggested SLOs

- Run create API availability >= 99.9%
- P95 run creation latency <= 2 seconds
- Node execution error rate <= 5%
- End-to-end run success rate >= 95% (excluding user-input validation failures)

## Alerting Rules

Alert rules are defined in `deploy/docker/prometheus-alerts.yml`:

- `XFlowsApiDown`
- `XFlowsWorkerDown`
- `XFlowsRunCreateLatencyHigh`
- `XFlowsNodeErrorRateHigh`

## Regression Evaluation Pipeline

- Golden test cases are stored in `tools/evals/testcases.json`.
- Evaluation script submits run requests to API and compares output heuristics.
- Release gate checks:
  - success ratio threshold
  - max allowed failures
  - latency percentile threshold
