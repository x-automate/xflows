"""Wave 3 tests: XWS tool node executors (docs 06 XU-2)."""

from __future__ import annotations

import unittest

from xflows_engine.context import NodeExecutionContext
from xflows_engine.executors.xws_tools import (
    XWS3Executor,
    XWSApigwRegisterExecutor,
    XWSAuditExecutor,
    XWSDmsIntrospectExecutor,
    XWSGatewayLLMExecutor,
    XWSIAMEvaluateExecutor,
    XWSLambdaInvokeExecutor,
    XWSRelayNotifyExecutor,
)


class FakeXwsClient:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[dict] = []
        self.responses = list(responses or [])

    def request(
        self,
        *,
        method: str,
        path: str,
        tool_class: str,
        run_id: str,
        json_body=None,
        params=None,
        idempotency_key=None,
        retry: bool = False,
    ) -> dict:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "tool_class": tool_class,
                "run_id": run_id,
                "json_body": json_body,
                "params": params,
                "idempotency_key": idempotency_key,
                "retry": retry,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True}


class ExplodingXwsClient(FakeXwsClient):
    def request(self, **kwargs) -> dict:
        raise RuntimeError("boom")


def _node(component_id: str, **params) -> dict:
    return {"id": "xws_1", "componentId": component_id, "params": params}


def _context(client) -> NodeExecutionContext:
    async def fake_llm_chat(prompt, system_prompt=None, model_hint=None, temperature=None):
        return {"content": "", "provider": "litellm", "model": "m", "usage": {}}

    async def fake_http_request(method: str, url: str) -> str:
        return f"{method}:{url}"

    return NodeExecutionContext(
        run_id="run_1",
        trace_id="trace_1",
        user_input="hello",
        llm_chat=fake_llm_chat,
        http_request=fake_http_request,
        runtime_config={},
        xws_client=client,
    )


class XWS3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_put_uses_bucket_and_retry(self) -> None:
        client = FakeXwsClient(responses=[{"value": "stored"}])
        node = _node("XWSS3", operation="put", key="out.py", body="print(1)")
        result = await XWS3Executor().execute(node, {"value": "x"}, _context(client))
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["method"], "PUT")
        self.assertEqual(call["path"], "/s3/apigen-artifacts/out.py")
        self.assertEqual(call["json_body"], {"body": "print(1)"})
        self.assertEqual(call["tool_class"], "s3")
        self.assertEqual(call["run_id"], "run_1")
        self.assertTrue(call["retry"])
        self.assertEqual(result.value, "stored")
        self.assertEqual(result.metadata["operation"], "put")
        self.assertEqual(result.metadata["key"], "out.py")
        self.assertEqual(result.metadata["toolClass"], "s3")

    async def test_get_has_no_body(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="get", key="out.py")
        await XWS3Executor().execute(node, {"value": "x"}, _context(client))
        call = client.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertIsNone(call["json_body"])
        self.assertIsNone(call["params"])

    async def test_list_versions_sends_params(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="list_versions", key="out.py")
        await XWS3Executor().execute(node, {"value": "x"}, _context(client))
        self.assertEqual(client.calls[0]["params"], {"versions": "true"})

    async def test_key_from_input_payload(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="get")
        await XWS3Executor().execute(node, {"key": "from-input.txt"}, _context(client))
        self.assertEqual(client.calls[0]["path"], "/s3/apigen-artifacts/from-input.txt")

    async def test_missing_key_raises(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="get")
        with self.assertRaisesRegex(ValueError, "key"):
            await XWS3Executor().execute(node, {"value": "x"}, _context(client))

    async def test_unsupported_operation_raises(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="delete", key="k")
        with self.assertRaisesRegex(ValueError, "delete"):
            await XWS3Executor().execute(node, {"value": "x"}, _context(client))

    async def test_missing_client_raises_runtime_error(self) -> None:
        node = _node("XWSS3", operation="get", key="k")
        with self.assertRaisesRegex(RuntimeError, "xws_client"):
            await XWS3Executor().execute(node, {"value": "x"}, _context(None))

    async def test_tool_class_param_override(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="get", key="k", toolClass="s3-tenant-a")
        result = await XWS3Executor().execute(node, {"value": "x"}, _context(client))
        self.assertEqual(client.calls[0]["tool_class"], "s3-tenant-a")
        self.assertEqual(result.metadata["toolClass"], "s3-tenant-a")

    async def test_bucket_param_override(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSS3", operation="get", key="k", bucket="other-bucket")
        await XWS3Executor().execute(node, {"value": "x"}, _context(client))
        self.assertEqual(client.calls[0]["path"], "/s3/other-bucket/k")


class XWSLambdaInvokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_invoke_sends_idempotency_key(self) -> None:
        client = FakeXwsClient(responses=[{"value": "rendered"}])
        node = _node(
            "XWSLambdaInvoke",
            functionName="render",
            bundleHash="abc123",
            payload={"x": 1},
        )
        result = await XWSLambdaInvokeExecutor().execute(node, {"value": "x"}, _context(client))
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/lambda/invoke/render")
        self.assertEqual(call["json_body"], {"payload": {"x": 1}, "bundleHash": "abc123"})
        self.assertEqual(call["idempotency_key"], "bundle-abc123")
        self.assertFalse(call["retry"])
        self.assertEqual(result.value, "rendered")
        self.assertEqual(result.metadata["functionName"], "render")

    async def test_missing_function_name_raises(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSLambdaInvoke", bundleHash="abc123")
        with self.assertRaisesRegex(ValueError, "functionName"):
            await XWSLambdaInvokeExecutor().execute(node, {"value": "x"}, _context(client))

    async def test_missing_bundle_hash_raises(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSLambdaInvoke", functionName="render")
        with self.assertRaisesRegex(ValueError, "bundleHash"):
            await XWSLambdaInvokeExecutor().execute(node, {"value": "x"}, _context(client))

    async def test_bundle_hash_from_input(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSLambdaInvoke", functionName="render")
        await XWSLambdaInvokeExecutor().execute(
            node, {"value": {}, "bundleHash": "in-hash"}, _context(client)
        )
        self.assertEqual(client.calls[0]["idempotency_key"], "bundle-in-hash")


class XWSIAMEvaluateTests(unittest.IsolatedAsyncioTestCase):
    async def test_allow_decision(self) -> None:
        client = FakeXwsClient(
            responses=[{"allowed": True, "decision": "allow"}]
        )
        node = _node(
            "XWSIAMEvaluate",
            principal="user-1",
            action="s3:PutObject",
            resource="apigen-artifacts/out.py",
        )
        result = await XWSIAMEvaluateExecutor().execute(node, {"value": "x"}, _context(client))
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/iam/evaluate")
        self.assertEqual(
            call["json_body"],
            {
                "principal": "user-1",
                "action": "s3:PutObject",
                "resource": "apigen-artifacts/out.py",
                "context": {},
            },
        )
        self.assertTrue(result.value)
        self.assertTrue(result.metadata["allowed"])
        self.assertEqual(result.metadata["decision"], "allow")

    async def test_empty_result_fails_closed(self) -> None:
        client = FakeXwsClient(responses=[{}])
        node = _node(
            "XWSIAMEvaluate", principal="p", action="a", resource="r"
        )
        result = await XWSIAMEvaluateExecutor().execute(node, {"value": "x"}, _context(client))
        self.assertFalse(result.value)
        self.assertFalse(result.metadata["allowed"])
        self.assertEqual(result.metadata["decision"], "deny")

    async def test_missing_args_raises(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSIAMEvaluate", principal="p", action="a")
        with self.assertRaisesRegex(ValueError, "resource"):
            await XWSIAMEvaluateExecutor().execute(node, {"value": "x"}, _context(client))

    async def test_args_from_input_payload(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSIAMEvaluate")
        await XWSIAMEvaluateExecutor().execute(
            node,
            {"principal": "p", "action": "a", "resource": "r"},
            _context(client),
        )
        self.assertEqual(client.calls[0]["json_body"]["principal"], "p")


class XWSRelayNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_notification_id(self) -> None:
        client = FakeXwsClient(responses=[{"notificationId": "n-1"}])
        node = _node("XWSRelayNotify", message="please review", deepLink="/runs/1")
        result = await XWSRelayNotifyExecutor().execute(node, {"value": "x"}, _context(client))
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/relay/notify")
        self.assertEqual(call["json_body"]["message"], "please review")
        self.assertEqual(call["json_body"]["deepLink"], "/runs/1")
        self.assertEqual(call["json_body"]["channel"], "console")
        self.assertEqual(
            result.value,
            {"notified": True, "parked": False, "notificationId": "n-1"},
        )
        self.assertFalse(result.metadata["parked"])

    async def test_failure_parks_the_gate(self) -> None:
        client = ExplodingXwsClient()
        node = _node("XWSRelayNotify", message="please review")
        result = await XWSRelayNotifyExecutor().execute(node, {"value": "x"}, _context(client))
        self.assertFalse(result.value["notified"])
        self.assertTrue(result.value["parked"])
        self.assertIn("boom", result.value["error"])
        self.assertTrue(result.metadata["parked"])

    async def test_message_from_input_value(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSRelayNotify")
        await XWSRelayNotifyExecutor().execute(
            node, {"value": "from input"}, _context(client)
        )
        self.assertEqual(client.calls[0]["json_body"]["message"], "from input")


class InertExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_dms_introspect_inert(self) -> None:
        node = _node("XWSDmsIntrospect")
        with self.assertRaises(NotImplementedError):
            await XWSDmsIntrospectExecutor().execute(node, {"value": "x"}, _context(None))

    async def test_apigw_register_inert(self) -> None:
        node = _node("XWSApigwRegister")
        with self.assertRaises(NotImplementedError):
            await XWSApigwRegisterExecutor().execute(node, {"value": "x"}, _context(None))


class XWSAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_posts_events_append(self) -> None:
        client = FakeXwsClient(responses=[{"id": "evt-1", "seq": 42}])
        node = _node("XWSAudit", action="xws:Test", resource="arn:xws:test:::x", result="denied")
        result = await XWSAuditExecutor().execute(node, {"value": "payload"}, _context(client))

        self.assertEqual(result.value, "evt-1")
        self.assertEqual(result.metadata["xwsTool"], "XWSAudit")
        self.assertEqual(client.calls[0]["method"], "POST")
        self.assertEqual(client.calls[0]["path"], "/events/append")
        self.assertEqual(client.calls[0]["tool_class"], "audit")
        self.assertEqual(client.calls[0]["json_body"]["action"], "xws:Test")
        self.assertEqual(client.calls[0]["json_body"]["resource"], "arn:xws:test:::x")
        self.assertEqual(client.calls[0]["json_body"]["result"], "denied")

    async def test_defaults_action_and_resource(self) -> None:
        client = FakeXwsClient(responses=[{"id": "evt-2"}])
        node = _node("XWSAudit")
        await XWSAuditExecutor().execute(node, {"value": "payload"}, _context(client))

        body = client.calls[0]["json_body"]
        self.assertEqual(body["action"], "xflows:AuditEvent")
        self.assertEqual(body["resource"], "arn:xws:xflows:::run/run_1")
        self.assertEqual(body["result"], "success")
        self.assertEqual(body["params"], {"value": "payload"})

    async def test_details_param_passed_through(self) -> None:
        client = FakeXwsClient(responses=[{"id": "evt-3"}])
        node = _node("XWSAudit", details={"foo": "bar"})
        await XWSAuditExecutor().execute(node, {"value": "payload"}, _context(client))

        self.assertEqual(client.calls[0]["json_body"]["params"], {"foo": "bar"})


class GatewayLLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_through_gateway_complete(self) -> None:
        client = FakeXwsClient(responses=[{"content": "hi", "model": "m1", "usage": {}}])
        node = _node("XWSGatewayLLM", prompt="classify this")
        result = await XWSGatewayLLMExecutor().execute(node, {"value": "x"}, _context(client))
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/v1/gateway/complete")
        self.assertEqual(call["tool_class"], "llm")
        self.assertEqual(call["run_id"], "run_1")
        self.assertTrue(call["retry"])
        self.assertEqual(call["json_body"]["prompt"], "classify this")
        self.assertNotIn("response_format", call["json_body"])
        self.assertEqual(result.value, "hi")
        self.assertEqual(result.metadata["model"], "m1")
        self.assertEqual(result.metadata["toolClass"], "llm")

    async def test_prompt_falls_back_to_input_value(self) -> None:
        client = FakeXwsClient(responses=[{"content": "ok"}])
        node = _node("XWSGatewayLLM")
        await XWSGatewayLLMExecutor().execute(node, {"value": "from input"}, _context(client))
        self.assertEqual(client.calls[0]["json_body"]["prompt"], "from input")

    async def test_empty_prompt_raises(self) -> None:
        client = FakeXwsClient()
        node = _node("XWSGatewayLLM")
        with self.assertRaises(ValueError):
            await XWSGatewayLLMExecutor().execute(node, {"value": "  "}, _context(client))

    async def test_structured_output_sends_strict_schema(self) -> None:
        client = FakeXwsClient(responses=[{"content": '{"archetype": "crud"}'}])
        schema = {
            "type": "object",
            "properties": {"archetype": {"type": "string"}},
            "required": ["archetype"],
        }
        node = _node("XWSGatewayLLM", prompt="classify", outputSchema=schema)
        result = await XWSGatewayLLMExecutor().execute(node, {}, _context(client))
        body = client.calls[0]["json_body"]
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(body["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(result.value, {"archetype": "crud"})
        self.assertTrue(result.metadata["schemaValidated"])

    async def test_schema_violation_raises(self) -> None:
        client = FakeXwsClient(responses=[{"content": '{"wrong": 1}'}])
        schema = {
            "type": "object",
            "properties": {"archetype": {"type": "string"}},
            "required": ["archetype"],
        }
        node = _node("XWSGatewayLLM", prompt="classify", outputSchema=schema)
        with self.assertRaises(ValueError):
            await XWSGatewayLLMExecutor().execute(node, {}, _context(client))

    async def test_non_json_content_with_schema_raises(self) -> None:
        client = FakeXwsClient(responses=[{"content": "not json at all"}])
        node = _node("XWSGatewayLLM", prompt="classify", outputSchema={"type": "object"})
        with self.assertRaises(ValueError):
            await XWSGatewayLLMExecutor().execute(node, {}, _context(client))

    async def test_model_and_options_forwarded(self) -> None:
        client = FakeXwsClient(responses=[{"content": "ok"}])
        node = _node(
            "XWSGatewayLLM",
            prompt="p",
            model="gpt-4o",
            temperature=0.2,
            maxTokens=512,
            system="be terse",
        )
        await XWSGatewayLLMExecutor().execute(node, {}, _context(client))
        body = client.calls[0]["json_body"]
        self.assertEqual(body["model"], "gpt-4o")
        self.assertEqual(body["temperature"], 0.2)
        self.assertEqual(body["maxTokens"], 512)
        self.assertEqual(body["system"], "be terse")


if __name__ == "__main__":
    unittest.main()
