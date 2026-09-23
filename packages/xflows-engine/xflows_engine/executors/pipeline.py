"""APIGen pipeline executors (docs 04 §2).

Three deterministic (no-LLM, no-secrets) executors for the apigen.generate
workflow:

- ``SchemaValidate``: validates an input payload against a JSON Schema
  (inline ``schema`` param or named ``outputSchema``). Fails loud so the
  workflow routes failures via edges/``when`` predicates.
- ``Codegen``: template-based code generation from an OpenAPI-style spec.
  Deterministic (no LLM): FastAPI endpoint stubs keyed off the spec's
  ``paths``. Returns a content-hash bundle ref.
- ``SubWorkflow``: spawns a child workflow (e.g. apigen.validate /
  apigen.deploy) through the ``start_child_workflow`` seam on the execution
  context (workers layer: ``workflow.start_child_workflow``).

None of these components appear in ``SECRET_BEARING_COMPONENTS``: they never
need provider credentials, so ``scoped_runtime_config`` strips secret-shaped
keys from their configs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult

_DEFAULT_CODEGEN_TEMPLATE = "fastapi-arc1@1.4.0"

_SCHEMA_TYPES = (
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
    "null",
)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _validate_against_schema(
    value: Any,
    schema: Any,
    path: str,
    errors: list[str],
) -> None:
    """Minimal, deterministic JSON Schema subset: type/required/properties/
    items/enum/min/max/length checks. Unknown keywords are ignored."""
    if not isinstance(schema, dict):
        return
    expected = schema.get("type")
    if isinstance(expected, str) and expected in _SCHEMA_TYPES:
        actual = _json_type(value)
        if expected == "number" and actual == "integer":
            actual = "number"
        if actual != expected:
            errors.append(f"{path}: expected type {expected!r}, got {actual!r}")
            return
    if isinstance(expected, list) and expected:
        actual = _json_type(value)
        if "number" in expected and actual == "integer":
            actual = "number"
        if actual not in expected:
            errors.append(f"{path}: expected type in {expected!r}, got {actual!r}")
            return
    if "enum" in schema and isinstance(schema["enum"], list) and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: length {len(value)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: length {len(value)} > maxLength {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value {value} > maximum {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: {len(value)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: {len(value)} items > maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_against_schema(item, item_schema, f"{path}[{index}]", errors)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key}: required property missing")
        if isinstance(properties, dict):
            for key, sub_schema in properties.items():
                if key in value:
                    _validate_against_schema(
                        value[key], sub_schema, f"{path}.{key}", errors
                    )


def _parse_payload(value: Any) -> Any:
    """Parse the incoming value if it is a JSON string; pass through else."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"payload is a string but not valid JSON: {error}") from error
    return value


def _require_schema(node: dict[str, Any], context: NodeExecutionContext) -> tuple[dict[str, Any], str]:
    """Resolve the schema from an inline ``schema`` param or a named
    ``outputSchema`` (looked up in runtime_config["schemas"]). Fail loud."""
    params = node.get("params", {}) or {}
    schema = params.get("schema")
    if isinstance(schema, dict):
        return schema, "inline"
    name = params.get("outputSchema")
    if isinstance(name, str) and name:
        schemas = context.runtime_config.get("schemas")
        named = schemas.get(name) if isinstance(schemas, dict) else None
        if isinstance(named, dict):
            return named, name
        raise ValueError(
            f"SchemaValidate node {node.get('id', '')!r}: named schema {name!r} "
            "not found in runtime_config.schemas"
        )
    raise ValueError(
        f"SchemaValidate node {node.get('id', '')!r}: requires a 'schema' "
        "(inline dict) or 'outputSchema' (name) param"
    )


class SchemaValidateExecutor(BaseNodeExecutor):
    component_ids = ("SchemaValidate",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        schema, schema_name = _require_schema(node, context)
        payload = _parse_payload(input_payload.get("value"))
        if not isinstance(payload, dict):
            raise ValueError(
                f"SchemaValidate node {node.get('id', '')!r}: payload must be a "
                f"JSON object, got {_json_type(payload)}"
            )
        errors: list[str] = []
        _validate_against_schema(payload, schema, "$", errors)
        if errors:
            raise ValueError(
                f"SchemaValidate node {node.get('id', '')!r} failed with "
                f"{len(errors)} violation(s): " + "; ".join(errors[:10])
            )
        return NodeExecutionResult(
            value=payload,
            metadata={
                "schemaValidate": {
                    "schema": schema_name,
                    "ok": True,
                },
            },
        )


def _render_endpoint(path: str, operations: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for method in sorted(operations):
        if method.lower() not in {"get", "post", "put", "patch", "delete"}:
            continue
        operation = operations[method] if isinstance(operations[method], dict) else {}
        summary = str(operation.get("summary") or operation.get("operationId") or path)
        lines.append(f"@app.{method.lower()}(\"{path}\")")
        lines.append(f"async def {method.lower()}_{path.replace('/', '_').strip('_')}(request: Request) -> Response:")
        lines.append(f"    \"\"\"{summary}\"\"\"")
        lines.append(f"    raise NotImplementedError  # TODO: implement {method.upper()} {path}")
        lines.append("")
    return lines


def _generate_fastapi(spec: dict[str, Any], template: str) -> dict[str, str]:
    """Generate deterministic FastAPI stubs from an OpenAPI-style spec."""
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError(
            f"Codegen: spec has no 'paths' object (or it is empty); "
            f"cannot generate stubs from template {template}"
        )
    header = (
        f"# Generated by xflows Codegen (template {template})\n"
        "from fastapi import FastAPI, Request, Response\n\n"
        "app = FastAPI(title=\"Generated API\")\n"
    )
    body: list[str] = []
    for path in sorted(paths):
        operations = paths[path] if isinstance(paths[path], dict) else {}
        body.extend(_render_endpoint(path, operations))
    content = header + "\n".join(body)
    return {"src/main.py": content}


class CodegenExecutor(BaseNodeExecutor):
    component_ids = ("Codegen",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        template = str(params.get("template") or _DEFAULT_CODEGEN_TEMPLATE)
        spec = _parse_payload(input_payload.get("value"))
        if not isinstance(spec, dict):
            raise ValueError(
                f"Codegen node {node.get('id', '')!r}: input must be an "
                f"OpenAPI-style spec object, got {_json_type(spec)}"
            )
        files = _generate_fastapi(spec, template)
        digest = hashlib.sha256()
        for file_path in sorted(files):
            digest.update(file_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(files[file_path].encode("utf-8"))
        bundle_hash = digest.hexdigest()
        code_bundle_ref = {
            "s3Key": f"runs/{context.run_id}/codegen/{bundle_hash[:12]}/bundle.tar.gz",
            "hash": bundle_hash,
            "template": template,
        }
        return NodeExecutionResult(
            value={
                "codeBundleRef": code_bundle_ref,
                "files": files,
                "hash": bundle_hash,
                "template": template,
            },
            metadata={
                "codegen": {
                    "hash": bundle_hash,
                    "template": template,
                    "fileCount": len(files),
                    "ref": code_bundle_ref,
                },
            },
        )


class SubWorkflowExecutor(BaseNodeExecutor):
    component_ids = ("SubWorkflow",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        if context.start_child_workflow is None:
            raise RuntimeError(
                "SubWorkflowExecutor requires a start_child_workflow seam on the "
                "execution context (workflow.start_child_workflow in the workers layer)"
            )
        params = node.get("params", {}) or {}
        workflow_name = params.get("workflowId") or params.get("workflow")
        if not isinstance(workflow_name, str) or not workflow_name:
            raise ValueError(
                f"SubWorkflow node {node.get('id', '')!r}: requires a 'workflowId' "
                "or 'workflow' param naming the child workflow"
            )
        child_runtime_config = (
            params.get("runtimeConfig")
            if isinstance(params.get("runtimeConfig"), dict)
            else {}
        )
        child_input = _parse_payload(input_payload.get("value"))
        result = await context.start_child_workflow({
            "workflowName": workflow_name,
            "input": child_input,
            "runtimeConfig": child_runtime_config,
        })
        if not isinstance(result, dict):
            raise ValueError(
                f"SubWorkflow node {node.get('id', '')!r}: child workflow seam "
                "returned a non-dict result"
            )
        status = str(result.get("status", "failed"))
        output = result.get("output", {})
        if status != "succeeded":
            raise ValueError(
                f"SubWorkflow node {node.get('id', '')!r}: child workflow "
                f"{workflow_name!r} ended with status {status!r}"
            )
        return NodeExecutionResult(
            value={
                "status": status,
                "workflow": workflow_name,
                "output": output,
            },
            metadata={
                "subWorkflow": {
                    "workflow": workflow_name,
                    "status": status,
                },
            },
        )
