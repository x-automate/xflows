from __future__ import annotations

import unittest

from xflows_engine.executors.llm import ChatLikeExecutor, LiteLlmExecutor, _chat_options
from xflows_engine.schema_validation import (
    build_repair_prompt,
    parse_json_output,
    parse_schema,
    validate_against_schema,
)


def _context(recorded: list | None = None, responses: list[dict] | None = None, runtime_config: dict | None = None):
    from xflows_engine.context import NodeExecutionContext

    calls: list[dict] = []
    responses = list(responses or [])

    async def fake_llm_chat(prompt, system_prompt=None, model_hint=None, temperature=0.2, **options):
        calls.append(
            {
                "prompt": prompt,
                "system": system_prompt,
                "model": model_hint,
                "temperature": temperature,
                **options,
            }
        )
        if responses:
            return responses.pop(0)
        return {
            "content": f"answer:{prompt}",
            "provider": "test",
            "model": model_hint or "fake-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    async def fake_http_request(method: str, url: str) -> str:
        return f"{method}:{url}"

    return (
        NodeExecutionContext(
            run_id="run_1",
            trace_id="trace_1",
            user_input="hello",
            llm_chat=fake_llm_chat,
            http_request=fake_http_request,
            runtime_config=runtime_config or {},
        ),
        calls,
    )


SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["verdict", "score"],
}


class SchemaValidationTests(unittest.TestCase):
    def test_parse_json_output_plain(self) -> None:
        value, error = parse_json_output('{"a": 1}')
        self.assertIsNone(error)
        self.assertEqual(value, {"a": 1})

    def test_parse_json_output_code_fence(self) -> None:
        value, error = parse_json_output('Sure!\n```json\n{"a": 1}\n```')
        self.assertIsNone(error)
        self.assertEqual(value, {"a": 1})

    def test_parse_json_output_prose_around(self) -> None:
        value, error = parse_json_output('The result is {"a": [1, 2, 3]} as requested.')
        self.assertIsNone(error)
        self.assertEqual(value, {"a": [1, 2, 3]})

    def test_parse_json_output_invalid(self) -> None:
        value, error = parse_json_output("no json here")
        self.assertIsNone(value)
        self.assertIn("not valid JSON", error)

    def test_validate_against_schema_happy(self) -> None:
        errors = validate_against_schema({"verdict": "approve", "score": 10}, SCHEMA)
        self.assertEqual(errors, [])

    def test_validate_against_schema_missing_required(self) -> None:
        errors = validate_against_schema({"verdict": "approve"}, SCHEMA)
        self.assertTrue(any("'score'" in e for e in errors))

    def test_validate_against_schema_enum(self) -> None:
        errors = validate_against_schema({"verdict": "maybe", "score": 10}, SCHEMA)
        self.assertTrue(any("not one of" in e for e in errors))

    def test_validate_against_schema_nested(self) -> None:
        schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "integer"}}}}
        errors = validate_against_schema({"items": [1, "two", 3]}, schema)
        self.assertTrue(any("items" in e and "'two'" in e for e in errors))

    def test_parse_schema_rejects_bad_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid JSON Schema"):
            parse_schema("{nope]")

    def test_parse_schema_rejects_non_object(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_schema("[1,2]")

    def test_build_repair_prompt_includes_errors(self) -> None:
        prompt = build_repair_prompt("original", SCHEMA, '{"verdict": "x"}', ["root: bad"])
        self.assertIn("original", prompt)
        self.assertIn("- root: bad", prompt)
        self.assertIn("JSON schema", prompt)


class ChatOptionsTests(unittest.TestCase):
    def test_max_tokens_and_stop(self) -> None:
        options = _chat_options({"max_tokens": 256, "stop": "END,STOP"})
        self.assertEqual(options, {"max_tokens": 256, "stop": ["END", "STOP"]})

    def test_empty_options(self) -> None:
        self.assertEqual(_chat_options({}), {})

    def test_invalid_max_tokens_ignored(self) -> None:
        self.assertEqual(_chat_options({"max_tokens": "soon"}), {})


class ChatLikeSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_chat_without_schema(self) -> None:
        executor = ChatLikeExecutor()
        context, calls = _context()
        node = {"id": "n1", "componentId": "LLM", "params": {"max_tokens": 256}}
        result = await executor.execute(node, {"value": "ping"}, context)
        self.assertEqual(result.value, "answer:ping")
        self.assertEqual(calls[0]["max_tokens"], 256)
        self.assertNotIn("response_format", calls[0])

    async def test_output_schema_valid_first_pass(self) -> None:
        executor = ChatLikeExecutor()
        context, calls = _context(
            responses=[
                {"content": '{"verdict": "approve", "score": 80}', "provider": "test", "model": "m", "usage": {}}
            ]
        )
        node = {"id": "n1", "componentId": "LLM", "params": {"outputSchema": '{"type": "object"}'}}
        result = await executor.execute(node, {"value": "classify this"}, context)
        self.assertEqual(result.value, {"verdict": "approve", "score": 80})
        self.assertEqual(result.metadata["schemaValidated"], True)
        self.assertEqual(result.metadata["repairAttempts"], 0)
        self.assertEqual(calls[0]["response_format"]["type"], "json_schema")

    async def test_output_schema_repaired_after_failure(self) -> None:
        executor = ChatLikeExecutor()
        context, calls = _context(
            responses=[
                {"content": "not json", "provider": "test", "model": "m", "usage": {}},
                {"content": '{"verdict": "approve", "score": 50}', "provider": "test", "model": "m", "usage": {}},
            ]
        )
        node = {"id": "n1", "componentId": "LLM", "params": {"outputSchema": '{"type": "object"}'}}
        result = await executor.execute(node, {"value": "classify"}, context)
        self.assertEqual(result.value, {"verdict": "approve", "score": 50})
        self.assertEqual(result.metadata["repairAttempts"], 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("JSON schema", calls[1]["prompt"])
        self.assertIn("not json", calls[1]["prompt"])

    async def test_output_schema_fails_loudly_after_repairs(self) -> None:
        executor = ChatLikeExecutor()
        context, _ = _context(
            responses=[
                {"content": "bad", "provider": "test", "model": "m", "usage": {}},
                {"content": "still bad", "provider": "test", "model": "m", "usage": {}},
            ]
        )
        node = {
            "id": "n1",
            "componentId": "LLM",
            "params": {"outputSchema": '{"type": "object"}', "maxRepairAttempts": 1},
        }
        with self.assertRaisesRegex(ValueError, "failed schema validation"):
            await executor.execute(node, {"value": "classify"}, context)

    async def test_non_strict_schema_returns_raw(self) -> None:
        executor = ChatLikeExecutor()
        context, _ = _context(responses=[{"content": "not json", "provider": "test", "model": "m", "usage": {}}])
        node = {
            "id": "n1",
            "componentId": "LLM",
            "params": {"outputSchema": '{"type": "object"}', "strictSchema": False},
        }
        result = await executor.execute(node, {"value": "classify"}, context)
        self.assertEqual(result.value, "not json")
        self.assertEqual(result.metadata["schemaValidated"], False)
        self.assertTrue(result.metadata["schemaErrors"])

    async def test_invalid_schema_raises_immediately(self) -> None:
        executor = ChatLikeExecutor()
        context, _ = _context()
        node = {"id": "n1", "componentId": "LLM", "params": {"outputSchema": "{nope]"}}
        with self.assertRaisesRegex(ValueError, "outputSchema"):
            await executor.execute(node, {"value": "x"}, context)


class LiteLlmSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_litellm_carries_api_base_and_schema(self) -> None:
        executor = LiteLlmExecutor()
        context, calls = _context(
            responses=[{"content": '{"ok": true}', "provider": "litellm", "model": "openai/gpt-4o-mini", "usage": {}}],
            runtime_config={"litellmBaseUrl": "http://litellm:4000"},
        )
        node = {
            "id": "n1",
            "componentId": "LiteLLM",
            "params": {"model": "openai/gpt-4o-mini", "outputSchema": '{"type": "object"}'},
        }
        result = await executor.execute(node, {"value": "ping"}, context)
        self.assertEqual(result.value, {"ok": True})
        self.assertEqual(result.metadata["apiBase"], "http://litellm:4000")
        self.assertEqual(result.metadata["schemaValidated"], True)


if __name__ == "__main__":
    unittest.main()
