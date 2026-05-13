from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .models import WorkflowDefinition
    from .nodes import NodeGraphRunner, normalize_workflow_graph


@workflow.defn(name="XFlowsWorkflow.run")
class XFlowsWorkflow:
    @workflow.run
    async def run(
        self,
        workflow_def_payload: dict[str, Any],
        user_input: str,
        run_id: str,
        trace_id: str,
        runtime_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            workflow_def = WorkflowDefinition.model_validate(workflow_def_payload)
            raw_nodes = [node.model_dump(mode="json") for node in workflow_def.nodes]
            raw_edges = [edge.model_dump(mode="json") for edge in workflow_def.edges]
            nodes, edges = normalize_workflow_graph(raw_nodes, raw_edges)
            runner = NodeGraphRunner(nodes=nodes, edges=edges, user_input=user_input)

            outputs, order = await runner.run(
                self._execute_node_activity(
                    run_id=run_id,
                    trace_id=trace_id,
                    runtime_config=runtime_config or {},
                )
            )
            output_node_id = runner.resolve_output_node_id(order)
            output_value = outputs.get(output_node_id, {}).get("value", "")
            await workflow.execute_activity(
                "xflows.complete_run",
                args=[run_id, trace_id, "succeeded", {"output": output_value}],
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            return {
                "runId": run_id,
                "traceId": trace_id,
                "status": "succeeded",
                "output": output_value,
            }
        except Exception as error:
            await workflow.execute_activity(
                "xflows.complete_run",
                args=[run_id, trace_id, "failed", {"error": str(error)}],
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            raise

    @staticmethod
    def _execute_node_activity(
        run_id: str,
        trace_id: str,
        runtime_config: dict[str, Any],
    ) -> Any:
        async def execute(node: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
            return await workflow.execute_activity(
                "xflows.execute_node",
                args=[node, input_payload, run_id, trace_id, runtime_config],
                schedule_to_close_timeout=timedelta(seconds=120),
                retry_policy=workflow.RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=20),
                    maximum_attempts=3,
                ),
            )

        return execute
