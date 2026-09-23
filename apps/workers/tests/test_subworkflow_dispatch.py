"""Wave 5 tests: SubWorkflow node dispatch (docs 06 XU-3, 04 §3)."""

from __future__ import annotations

import unittest
from typing import Any

from app.workflows import _start_dag_child, _run_subworkflow_node
from test_apigen_workflows import ApiGenTestBase

INLINE_DEFINITION = {"name": "helper", "nodes": [{"id": "in"}], "edges": []}


class SubworkflowDispatchTests(ApiGenTestBase):
    async def test_inline_definition_dict_input_serialized(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowDefinition": dict(INLINE_DEFINITION)}}

        result = await _run_subworkflow_node(node, {"value": {"a": 1}}, "run1", "trace1", {"k": "v"})

        self.assertEqual(result, {"value": {"done": True}})
        name, args, kwargs = self.child_calls[0]
        self.assertEqual(name, "XFlowsWorkflow.run")
        self.assertEqual(args[0], INLINE_DEFINITION)
        self.assertEqual(args[1], '{"a": 1}')
        self.assertEqual(args[2], "run1:sw1")
        self.assertEqual(args[3], "trace1")
        self.assertEqual(args[4], {"k": "v"})
        self.assertEqual(kwargs["id"], "run1:sw1")

    async def test_inline_definition_string_input_passthrough(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowDefinition": dict(INLINE_DEFINITION)}}

        result = await _run_subworkflow_node(node, {"value": "hello"}, "run1", "trace1", None)

        self.assertEqual(result, {"value": {"done": True}})
        self.assertEqual(self.child_calls[0][1][1], "hello")

    async def test_registry_dispatch_validate(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "apigen.validate"}}

        result = await _run_subworkflow_node(node, {"value": {"bundleHash": "h1"}}, "run1", "trace1", None)

        self.assertEqual(result, {"value": {"ok": True}})
        name, args, kwargs = self.child_calls[0]
        self.assertEqual(name, "ApiGenValidateWorkflow.run")
        self.assertEqual(args[0], {"bundleHash": "h1"})
        self.assertEqual(args[1], "run1")
        self.assertEqual(args[3], {})
        self.assertEqual(kwargs["id"], "run1:sw1")
        self.assertEqual(self.load_workflow_calls, [])

    async def test_registry_dispatch_deploy(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "apigen.deploy"}}

        result = await _run_subworkflow_node(node, {"value": {"bundleHash": "h1"}}, "run1", "trace1", None)

        self.assertEqual(result, {"value": {"manifest": {"url": "https://x"}}})
        self.assertEqual(self.child_calls[0][0], "ApiGenDeployWorkflow.run")

    async def test_registry_dispatch_wraps_string_input(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "apigen.validate"}}

        result = await _run_subworkflow_node(node, {"value": "hi"}, "run1", "trace1", None)

        self.assertEqual(result, {"value": {"ok": True}})
        self.assertEqual(self.child_calls[0][1][0], {"value": "hi"})

    async def test_runtime_config_override_merged(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())
        node = {
            "id": "sw1",
            "componentId": "SubWorkflow",
            "params": {"workflowId": "apigen.validate", "runtimeConfig": {"sandboxRef": "arn:sb"}},
        }

        await _run_subworkflow_node(node, {"value": {"bundleHash": "h1"}}, "run1", "trace1", {"principal": "p1", "x": 1})

        self.assertEqual(
            self.child_calls[0][1][3],
            {"principal": "p1", "x": 1, "sandboxRef": "arn:sb"},
        )

    async def test_stored_workflow_wrapper_shape(self) -> None:
        self.load_workflow_payload["wf-store"] = {"definition": dict(INLINE_DEFINITION)}
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "wf-store"}}

        result = await _run_subworkflow_node(node, {"value": "hi"}, "run1", "trace1", None)

        self.assertEqual(result, {"value": {"done": True}})
        self.assertEqual(len(self.load_workflow_calls), 1)
        self.assertEqual(self.load_workflow_calls[0][1][0], "wf-store")
        self.assertEqual(self.child_calls[0][1][0], INLINE_DEFINITION)
        self.assertEqual(self.child_calls[0][1][2], "run1:sw1")

    async def test_stored_workflow_bare_shape(self) -> None:
        self.load_workflow_payload["wf-bare"] = dict(INLINE_DEFINITION)
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "wf-bare"}}

        result = await _run_subworkflow_node(node, {"value": "hi"}, "run1", "trace1", None)

        self.assertEqual(result, {"value": {"done": True}})
        self.assertEqual(self.child_calls[0][1][0], INLINE_DEFINITION)

    async def test_stored_workflow_without_definition_fails(self) -> None:
        self.load_workflow_payload["wf-bad"] = {"irrelevant": True}
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "wf-bad"}}

        with self.assertRaises(ValueError) as ctx:
            await _run_subworkflow_node(node, {"value": "hi"}, "run1", "trace1", None)
        self.assertEqual(str(ctx.exception), "workflow 'wf-bad' has no stored definition")
        self.assertEqual(self.child_calls, [])

    async def test_missing_workflow_id_fails_without_calls(self) -> None:
        self.install_pipeline(self.make_activity_handler(), self.make_child_handler())
        node = {"id": "sw9", "componentId": "SubWorkflow", "params": {}}

        with self.assertRaises(ValueError) as ctx:
            await _run_subworkflow_node(node, {"value": "hi"}, "run1", "trace1", None)
        self.assertEqual(str(ctx.exception), "subworkflow node 'sw9' is missing a workflow id")
        self.assertEqual(self.activity_calls, [])
        self.assertEqual(self.load_workflow_calls, [])
        self.assertEqual(self.child_calls, [])

    async def test_child_failure_raises(self) -> None:
        async def failing_child(name: str, args: list, kwargs: dict) -> dict:
            return {"status": "failed", "output": {"error": "x"}}

        self.install_pipeline(self._noop_activity_handler, failing_child)
        node = {"id": "sw1", "componentId": "SubWorkflow", "params": {"workflowId": "apigen.validate"}}

        with self.assertRaises(ValueError) as ctx:
            await _run_subworkflow_node(node, {"value": {"bundleHash": "h1"}}, "run1", "trace1", None)
        self.assertEqual(
            str(ctx.exception),
            "subworkflow node 'sw1' ('apigen.validate') did not succeed",
        )

    async def test_start_dag_child(self) -> None:
        self.install_pipeline(self._noop_activity_handler, self.make_child_handler())

        result = await _start_dag_child("runX", "trace1", dict(INLINE_DEFINITION), "hi", {"k": 1})

        self.assertEqual(result, {"status": "succeeded", "output": {"done": True}})
        name, args, kwargs = self.child_calls[0]
        self.assertEqual(name, "XFlowsWorkflow.run")
        self.assertEqual(args[0], INLINE_DEFINITION)
        self.assertEqual(args[1], "hi")
        self.assertEqual(args[2], "runX")
        self.assertEqual(kwargs["id"], "runX")


if __name__ == "__main__":
    unittest.main()
