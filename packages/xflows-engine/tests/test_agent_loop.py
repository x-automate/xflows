"""Wave 3 tests: bounded AgentLoop executor (docs 06 XU-3)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from xflows_engine.context import NodeExecutionContext
from xflows_engine.executors.agent_loop import AGENT_SYSTEM_PROMPT, AgentLoopExecutor


class FakeChat:
    def __init__(self, envelopes: list[dict] | None = None) -> None:
        self.envelopes = list(envelopes or [])
        self.calls: list[dict] = []

    async def __call__(self, prompt, system_prompt=None, model_hint=None, temperature=None):
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "model_hint": model_hint,
                "temperature": temperature,
            }
        )
        if self.envelopes:
            return self.envelopes.pop(0)
        return self._final_envelope()

    @staticmethod
    def _final_envelope() -> dict:
        return {
            "content": json.dumps({"action": "final", "output": "default-final"}),
            "provider": "litellm",
            "model": "test-model",
            "usage": {"total_tokens": 10},
        }


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


def _node(**overrides) -> dict:
    params = {
        "allowlist": ["s3", "lambda", "iam", "relay"],
        "maxIterations": 5,
        "tokenCap": 20000,
        "timeoutS": 60,
    }
    params.update(overrides.pop("params", {}))
    node = {"id": "agent_1", "componentId": "AgentLoop", "params": params}
    node.update(overrides)
    return node


def _context(chat: FakeChat, client: FakeXwsClient | None, runtime_config: dict | None = None) -> NodeExecutionContext:
    async def fake_http_request(method: str, url: str) -> str:
        return f"{method}:{url}"

    return NodeExecutionContext(
        run_id="run_1",
        trace_id="trace_1",
        user_input="hello",
        llm_chat=chat,
        http_request=fake_http_request,
        runtime_config=runtime_config or {},
        xws_client=client,
    )


def _tool_envelope(tool: str, tool_class: str, args: dict | None = None, tokens: int = 10) -> dict:
    return {
        "content": json.dumps({"action": "tool", "toolClass": tool_class, "tool": tool, "args": args or {}}),
        "provider": "litellm",
        "model": "test-model",
        "usage": {"total_tokens": tokens},
    }


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_on_first_envelope(self) -> None:
        chat = FakeChat()
        client = FakeXwsClient()
        result = await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(result.value, "default-final")
        loop_meta = result.metadata["agentLoop"]
        self.assertEqual(loop_meta["stopReason"], "final")
        self.assertEqual(loop_meta["iterations"], 1)
        self.assertEqual(len(chat.calls), 1)
        self.assertEqual(client.calls, [])
        self.assertIn("s3, lambda, iam, relay", chat.calls[0]["system_prompt"])
        self.assertEqual(result.metadata["model"], "test-model")
        self.assertEqual(result.metadata["provider"], "litellm")

    async def test_tool_call_then_final(self) -> None:
        chat = FakeChat([_tool_envelope("XWSS3", "s3", {"operation": "put", "key": "out.py", "body": "print(1)"})])
        client = FakeXwsClient(responses=[{"ok": True}])
        result = await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(result.value, "default-final")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["method"], "PUT")
        self.assertEqual(call["path"], "/s3/apigen-artifacts/out.py")
        self.assertEqual(call["json_body"], {"body": "print(1)"})
        self.assertEqual(call["tool_class"], "s3")
        self.assertEqual(call["run_id"], "run_1")
        self.assertTrue(call["retry"])
        loop_meta = result.metadata["agentLoop"]
        self.assertEqual(loop_meta["stopReason"], "final")
        self.assertEqual(loop_meta["iterations"], 2)
        tool_entries = [e for e in loop_meta["transcript"] if e["type"] == "tool"]
        self.assertEqual(len(tool_entries), 1)
        self.assertEqual(tool_entries[0]["observation"], {"ok": True})
        # Observation is fed back into the next prompt (JSON message list).
        second_prompt = chat.calls[1]["prompt"]
        self.assertIn('\\"observation\\"', second_prompt)

    async def test_allowlist_deny_is_observation_not_exception(self) -> None:
        chat = FakeChat([_tool_envelope("XWSLambdaInvoke", "lambda", {"functionName": "f", "bundleHash": "h"})])
        client = FakeXwsClient()
        node = _node(params={"allowlist": ["s3"]})
        result = await AgentLoopExecutor().execute(node, {"value": "hello"}, _context(chat, client))
        self.assertEqual(client.calls, [])
        tool_entries = [e for e in result.metadata["agentLoop"]["transcript"] if e["type"] == "tool"]
        self.assertEqual(len(tool_entries), 1)
        self.assertEqual(
            tool_entries[0]["observation"],
            {"error": "toolClass 'lambda' is not in this node's allowlist"},
        )

    async def test_unknown_tool_with_allowed_class(self) -> None:
        chat = FakeChat([_tool_envelope("XWSBogus", "s3", {"key": "k"})])
        client = FakeXwsClient()
        result = await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(client.calls, [])
        tool_entries = [e for e in result.metadata["agentLoop"]["transcript"] if e["type"] == "tool"]
        self.assertEqual(tool_entries[0]["observation"], {"error": "unknown tool 'XWSBogus'"})

    async def test_arg_keys_are_filtered(self) -> None:
        chat = FakeChat(
            [
                _tool_envelope(
                    "XWSS3",
                    "s3",
                    {"operation": "put", "key": "k.txt", "body": "b", "evil": "inject"},
                )
            ]
        )
        client = FakeXwsClient()
        await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["json_body"], {"body": "b"})

    async def test_lambda_dispatch_idempotency_key(self) -> None:
        chat = FakeChat(
            [
                _tool_envelope(
                    "XWSLambdaInvoke",
                    "lambda",
                    {"functionName": "render", "bundleHash": "abc123", "payload": {"x": 1}},
                )
            ]
        )
        client = FakeXwsClient()
        await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], "/lambda/invoke/render")
        self.assertEqual(call["idempotency_key"], "bundle-abc123")
        self.assertEqual(call["json_body"], {"payload": {"x": 1}, "bundleHash": "abc123"})

    async def test_iam_dispatch_missing_args_raises_observation(self) -> None:
        chat = FakeChat([_tool_envelope("XWSIAMEvaluate", "iam", {"principal": "p"})])
        client = FakeXwsClient()
        result = await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(client.calls, [])
        tool_entries = [e for e in result.metadata["agentLoop"]["transcript"] if e["type"] == "tool"]
        self.assertIn("error", tool_entries[0]["observation"])

    async def test_token_cap_stops_loop(self) -> None:
        chat = FakeChat(
            [
                _tool_envelope("XWSS3", "s3", {"operation": "get", "key": "a"}, tokens=100),
                _tool_envelope("XWSS3", "s3", {"operation": "get", "key": "b"}, tokens=100),
            ]
        )
        client = FakeXwsClient()
        node = _node(params={"tokenCap": 150})
        result = await AgentLoopExecutor().execute(node, {"value": "hello"}, _context(chat, client))
        loop_meta = result.metadata["agentLoop"]
        self.assertEqual(loop_meta["stopReason"], "token_cap")
        self.assertEqual(loop_meta["iterations"], 2)
        self.assertEqual(loop_meta["tokensUsed"], 200)
        self.assertEqual(loop_meta["tokenCap"], 150)

    async def test_max_iterations_bound(self) -> None:
        chat = FakeChat(
            [
                _tool_envelope("XWSS3", "s3", {"operation": "get", "key": "a"}),
                _tool_envelope("XWSS3", "s3", {"operation": "get", "key": "b"}),
            ]
        )
        client = FakeXwsClient()
        node = _node(params={"maxIterations": 2})
        result = await AgentLoopExecutor().execute(node, {"value": "hello"}, _context(chat, client))
        loop_meta = result.metadata["agentLoop"]
        self.assertEqual(loop_meta["stopReason"], "max_iterations")
        self.assertEqual(loop_meta["iterations"], 2)
        self.assertEqual(len(client.calls), 2)

    async def test_timeout_stops_loop(self) -> None:
        chat = FakeChat()
        client = FakeXwsClient()
        node = _node(params={"timeoutS": 60})
        with mock.patch("xflows_engine.executors.agent_loop.time.monotonic", side_effect=[0, 1000]):
            result = await AgentLoopExecutor().execute(node, {"value": "hello"}, _context(chat, client))
        loop_meta = result.metadata["agentLoop"]
        self.assertEqual(loop_meta["stopReason"], "timeout")
        self.assertEqual(loop_meta["iterations"], 0)
        self.assertEqual(len(chat.calls), 0)

    async def test_invalid_envelope_stops_loop(self) -> None:
        chat = FakeChat([{"content": "not json at all", "provider": "litellm", "model": "m", "usage": {}}])
        client = FakeXwsClient()
        result = await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        loop_meta = result.metadata["agentLoop"]
        self.assertEqual(loop_meta["stopReason"], "invalid_envelope")
        self.assertIn("invalid envelope", result.value)

    async def test_unknown_action_stops_loop(self) -> None:
        chat = FakeChat(
            [
                {
                    "content": json.dumps({"action": "dance"}),
                    "provider": "litellm",
                    "model": "m",
                    "usage": {},
                }
            ]
        )
        client = FakeXwsClient()
        result = await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(result.metadata["agentLoop"]["stopReason"], "invalid_action")

    async def test_missing_xws_client_raises(self) -> None:
        chat = FakeChat()
        with self.assertRaisesRegex(RuntimeError, "xws_client"):
            await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, None))

    async def test_allowlist_from_runtime_config(self) -> None:
        chat = FakeChat()
        client = FakeXwsClient()
        runtime = {"xwsAllowlist": "s3, lambda"}
        await AgentLoopExecutor().execute(_node(params={"allowlist": None}), {"value": "hi"}, _context(chat, client, runtime))
        self.assertIn("s3, lambda", chat.calls[0]["system_prompt"])

    async def test_tool_class_defaulted_from_tool_name(self) -> None:
        envelope = {
            "content": json.dumps({"action": "tool", "tool": "XWSS3", "args": {"operation": "get", "key": "k"}}),
            "provider": "litellm",
            "model": "m",
            "usage": {},
        }
        chat = FakeChat([envelope])
        client = FakeXwsClient()
        await AgentLoopExecutor().execute(_node(), {"value": "hello"}, _context(chat, client))
        self.assertEqual(client.calls[0]["tool_class"], "s3")

    def test_system_prompt_lists_allowlist(self) -> None:
        self.assertIn("{allowlist}", AGENT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
