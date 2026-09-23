from __future__ import annotations

import json
from typing import Any

try:
    from jsonschema import Draft202012Validator

    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - exercised by absence of the optional dep
    _HAS_JSONSCHEMA = False


def parse_json_output(text: Any) -> tuple[Any, str | None]:
    if isinstance(text, (dict, list)):
        return text, None
    raw = str(text).strip()
    if not raw:
        return None, "empty response"
    candidates = [raw]
    start_candidates = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end > start:
            start_candidates.append(raw[start : end + 1])
    candidates.extend(start_candidates)
    for candidate in candidates:
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError:
            continue
    return None, f"response is not valid JSON: {raw[:200]}"


def validate_against_schema(value: Any, schema: dict[str, Any]) -> list[str]:
    if _HAS_JSONSCHEMA:
        validator = Draft202012Validator(schema)
        return [
            f"{list(error.absolute_path) or ['root']}: {error.message}"
            for error in validator.iter_errors(value)
        ]
    return _validate_subset(value, schema, "$")


def parse_schema(raw: Any) -> dict[str, Any]:
    if raw is None or str(raw).strip() == "":
        raise ValueError("outputSchema is empty")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as error:
        raise ValueError(f"outputSchema must be valid JSON Schema: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("outputSchema must be a JSON object")
    return parsed


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    python_type = _TYPE_MAP.get(expected)
    if python_type is None:
        return True
    return isinstance(value, python_type)


def _validate_subset(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_check_type(value, item) for item in expected_type):
            errors.append(f"{path}: expected type in {expected_type}, got {type(value).__name__}")
            return errors
    elif expected_type is not None:
        if not _check_type(value, str(expected_type)):
            errors.append(f"{path}: expected type {expected_type}, got {type(value).__name__}")
            return errors

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        errors.append(f"{path}: value {value!r} is not one of {enum!r}")

    minimum = schema.get("minimum")
    if minimum is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < minimum:
            errors.append(f"{path}: value {value} is less than minimum {minimum}")
    maximum = schema.get("maximum")
    if maximum is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > maximum:
            errors.append(f"{path}: value {value} is greater than maximum {maximum}")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"{path}: string shorter than minLength {min_length}")
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > max_length:
            errors.append(f"{path}: string longer than maxLength {max_length}")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties") or {}
        for key, item in value.items():
            sub_schema = properties.get(key)
            if sub_schema is None:
                if schema.get("additionalProperties") is False:
                    errors.append(f"{path}: unexpected property {key!r}")
                continue
            errors.extend(_validate_subset(item, sub_schema, f"{path}.{key}"))

    if isinstance(value, list):
        items_schema = schema.get("items")
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: fewer than minItems {min_items}")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: more than maxItems {max_items}")
        if items_schema:
            for idx, item in enumerate(value):
                errors.extend(_validate_subset(item, items_schema, f"{path}[{idx}]"))

    return errors


def build_repair_prompt(
    original_prompt: str,
    schema: dict[str, Any],
    raw_output: str,
    errors: list[str],
) -> str:
    lines = [
        "Your previous response did not satisfy the required JSON schema.",
        "",
        "Original request:",
        original_prompt,
        "",
        "Required JSON schema:",
        json.dumps(schema, indent=2),
        "",
        "Previous output:",
        raw_output[:4000],
        "",
        "Validation errors:",
    ]
    for error in errors:
        lines.append(f"- {error}")
    lines.append("")
    lines.append("Respond with ONLY the corrected JSON that satisfies the schema.")
    return "\n".join(lines)
