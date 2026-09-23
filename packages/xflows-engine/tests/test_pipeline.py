"""Wave 5 tests: APIGen pipeline executors (docs 04 §2).

SchemaValidate / Codegen / SubWorkflow are deterministic (no LLM, no secrets).
SubWorkflow is exercised through the ``start_child_workflow`` seam, mirroring
the Approval seam pattern.
"""

from __future__ import annotations

import json
import unittest

from xflows_engine import create_default_registry
from xflows_engine.context import NodeExecutionContext
from xflows_engine.executors.pipeline import (
    CodegenExecutor,
    SchemaValidateExecutor,
    SubWorkflowExecutor,
)


def _context(**seams) -> NodeExecutionContext:
    async def fake_llm_chat(*args, **kwargs):
        return {"content": "", "provider": "test", "model": "m", "usage": {}}

    async def fake_http(method: str, url: str) -> str:
        return f"{method}:{url}"

    return NodeExecutionContext(
        run_id="run_9",
        trace_id="t5",
        user_input="hello",
        llm_chat=fake_llm_chat,
        http_request=fake_http,
        runtime_config=seams.pop("runtime_config", {}),
        **seams,
    )


def _node(component_id: str, **params) -> dict:
    return {"id": "n1", "componentId": component_id, "params": params}


_SCHEMA = {
    "type": "object",
    "required": ["name", "version"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "pattern": "ignored"},
        "retries": {"type": "integer", "minimum": 0, "maximum": 5},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


class SchemaValidateExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_payload_passes(self) -> None:
        payload = {"name": "widget", "version": "1.0.0", "retries": 2, "tags": ["a"]}
        result = await SchemaValidateExecutor().execute(
            _node("SchemaValidate", schema=_SCHEMA),
            {"value": payload},
            _context(),
        )
        self.assertEqual(result.value, payload)
        self.assertEqual(result.metadata["schemaValidate"]["ok"], True)
        self.assertEqual(result.metadata["schemaValidate"]["schema"], "inline")

    async def test_json_string_payload_is_parsed(self) -> None:
        result = await SchemaValidateExecutor().execute(
            _node("SchemaValidate", schema=_SCHEMA),
            {"value": json.dumps({"name": "w", "version": "1.0"})},
            _context(),
        )
        self.assertEqual(result.value, {"name": "w", "version": "1.0"})

    async def test_missing_required_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "required property missing"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate", schema=_SCHEMA),
                {"value": {"name": "w"}},
                _context(),
            )

    async def test_type_violation_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected type"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate", schema=_SCHEMA),
                {"value": {"name": "w", "version": "1.0", "retries": "many"}},
                _context(),
            )

    async def test_minimum_violation_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "minimum"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate", schema=_SCHEMA),
                {"value": {"name": "w", "version": "1.0", "retries": -1}},
                _context(),
            )

    async def test_non_object_payload_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON object"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate", schema=_SCHEMA),
                {"value": [1, 2, 3]},
                _context(),
            )

    async def test_named_schema_resolved_from_runtime_config(self) -> None:
        context = _context(runtime_config={"schemas": {"stage1": _SCHEMA}})
        result = await SchemaValidateExecutor().execute(
            _node("SchemaValidate", outputSchema="stage1"),
            {"value": {"name": "w", "version": "1.0"}},
            context,
        )
        self.assertEqual(result.metadata["schemaValidate"]["schema"], "stage1")

    async def test_named_schema_missing_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "not found"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate", outputSchema="nope"),
                {"value": {}},
                _context(),
            )

    async def test_no_schema_param_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate"), {"value": {}}, _context()
            )

    async def test_invalid_json_string_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            await SchemaValidateExecutor().execute(
                _node("SchemaValidate", schema=_SCHEMA),
                {"value": "{not json"},
                _context(),
            )


_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/widgets": {
            "post": {"summary": "Create widget", "operationId": "createWidget"},
            "get": {"summary": "List widgets"},
        },
        "/widgets/{id}": {
            "get": {"summary": "Get widget"},
        },
    },
}


class CodegenExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_generates_stubs_and_bundle_ref(self) -> None:
        result = await CodegenExecutor().execute(
            _node("Codegen", template="fastapi-arc1@1.4.0"),
            {"value": _SPEC},
            _context(),
        )
        ref = result.value["codeBundleRef"]
        self.assertEqual(ref["template"], "fastapi-arc1@1.4.0")
        self.assertEqual(len(ref["hash"]), 64)
        self.assertTrue(ref["s3Key"].startswith("runs/run_9/codegen/"))
        main = result.value["files"]["src/main.py"]
        self.assertIn('@app.post("/widgets")', main)
        self.assertIn('@app.get("/widgets")', main)
        self.assertIn('@app.get("/widgets/{id}")', main)
        self.assertEqual(result.value["hash"], result.value["codeBundleRef"]["hash"])
        self.assertEqual(result.metadata["codegen"]["fileCount"], 1)

    async def test_deterministic_same_spec_same_hash(self) -> None:
        first = await CodegenExecutor().execute(
            _node("Codegen"), {"value": _SPEC}, _context()
        )
        second = await CodegenExecutor().execute(
            _node("Codegen"), {"value": _SPEC}, _context()
        )
        self.assertEqual(first.value["hash"], second.value["hash"])

    async def test_default_template_used(self) -> None:
        result = await CodegenExecutor().execute(
            _node("Codegen"), {"value": _SPEC}, _context()
        )
        self.assertEqual(result.value["template"], "fastapi-arc1@1.4.0")

    async def test_json_string_spec_is_parsed(self) -> None:
        result = await CodegenExecutor().execute(
            _node("Codegen"), {"value": json.dumps(_SPEC)}, _context()
        )
        self.assertIn("src/main.py", result.value["files"])

    async def test_spec_without_paths_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "paths"):
            await CodegenExecutor().execute(
                _node("Codegen"), {"value": {"openapi": "3.0.0"}}, _context()
            )

    async def test_non_object_input_fails_loud(self) -> None:
        with self.assertRaisesRegex(ValueError, "OpenAPI-style spec"):
            await CodegenExecutor().execute(
                _node("Codegen"), {"value": ["not", "a", "spec"]}, _context()
            )


class SubWorkflowExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawns_child_and_returns_output(self) -> None:
        seen: list[dict] = []

        async def seam(request: dict) -> dict:
            seen.append(request)
            return {"status": "succeeded", "output": {"lint": "clean"}}

        result = await SubWorkflowExecutor().execute(
            _node("SubWorkflow", workflowId="apigen.validate"),
            {"value": {"hash": "abc"}},
            _context(start_child_workflow=seam),
        )
        request = seen[0]
        self.assertEqual(request["workflowName"], "apigen.validate")
        self.assertEqual(request["input"], {"hash": "abc"})
        self.assertEqual(request["runtimeConfig"], {})
        self.assertEqual(result.value["status"], "succeeded")
        self.assertEqual(result.value["output"], {"lint": "clean"})
        self.assertEqual(result.metadata["subWorkflow"]["workflow"], "apigen.validate")

    async def test_child_failure_fails_loud(self) -> None:
        async def seam(request: dict) -> dict:
            return {"status": "failed", "output": {"error": "lint"}}

        with self.assertRaisesRegex(ValueError, "failed"):
            await SubWorkflowExecutor().execute(
                _node("SubWorkflow", workflow="apigen.validate"),
                {"value": {}},
                _context(start_child_workflow=seam),
            )

    async def test_missing_seam_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "start_child_workflow"):
            await SubWorkflowExecutor().execute(
                _node("SubWorkflow", workflowId="apigen.validate"),
                {"value": {}},
                _context(),
            )

    async def test_missing_workflow_param_fails_loud(self) -> None:
        async def seam(request: dict) -> dict:
            return {"status": "succeeded", "output": {}}

        with self.assertRaisesRegex(ValueError, "workflowId"):
            await SubWorkflowExecutor().execute(
                _node("SubWorkflow"), {"value": {}}, _context(start_child_workflow=seam)
            )

    async def test_runtime_config_param_passed_through(self) -> None:
        seen: list[dict] = []

        async def seam(request: dict) -> dict:
            seen.append(request)
            return {"status": "succeeded", "output": {}}

        await SubWorkflowExecutor().execute(
            _node("SubWorkflow", workflowId="apigen.deploy", runtimeConfig={"env": "prod"}),
            {"value": {}},
            _context(start_child_workflow=seam),
        )
        self.assertEqual(seen[0]["runtimeConfig"], {"env": "prod"})


class RegistryWiringTests(unittest.TestCase):
    def test_new_executors_are_registered(self) -> None:
        registry = create_default_registry()
        for component_id in ("SchemaValidate", "Codegen", "SubWorkflow"):
            executor = registry._executors.get(component_id)
            self.assertIsNotNone(executor, component_id)

    def test_pipeline_components_not_secret_bearing(self) -> None:
        from xflows_engine.context import SECRET_BEARING_COMPONENTS

        for component_id in ("SchemaValidate", "Codegen", "SubWorkflow"):
            self.assertNotIn(component_id, SECRET_BEARING_COMPONENTS)

    def test_runtime_config_secrets_stripped_for_pipeline_nodes(self) -> None:
        from xflows_engine.context import scoped_runtime_config

        scoped = scoped_runtime_config(
            "Codegen", {"template": "x", "apiKey": "s3cret"}
        )
        self.assertNotIn("apiKey", scoped)
        self.assertEqual(scoped["template"], "x")


if __name__ == "__main__":
    unittest.main()
