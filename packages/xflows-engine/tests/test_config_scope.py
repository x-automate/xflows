"""Wave 4 tests: per-node runtime-config scoping (fix XF-06)."""

from __future__ import annotations

import unittest

from xflows_engine.context import (
    SECRET_BEARING_COMPONENTS,
    SECRET_KEY_PATTERN,
    scoped_runtime_config,
)

CONFIG = {
    "litellmApiKey": "sk-super-secret",
    "litellmModel": "gpt-4o-mini",
    "litellmBaseUrl": "http://litellm:4000",
    "temperature": 0.2,
    "xwsAllowlist": "s3,relay",
    "secretPromptHint": "bleh",
    "authToken": "tok-1",
    "passwordHint": "pw",
    "hasOpenAIKey": True,
}


class SecretPatternTests(unittest.TestCase):
    def test_matches_secret_shaped_keys(self) -> None:
        for key in ("litellmApiKey", "authToken", "dbPassword", "clientSecret", "vaultToken"):
            self.assertTrue(SECRET_KEY_PATTERN.search(key), key)

    def test_ignores_non_secret_keys(self) -> None:
        for key in ("hasOpenAIKey", "litellmModel", "temperature", "xwsAllowlist"):
            self.assertFalse(SECRET_KEY_PATTERN.search(key), key)

    def test_max_tokens_is_treated_as_secret_shaped(self) -> None:
        # "maxTokens" contains "token"; stripping it from non-LLM nodes is
        # semantically fine — it is an LLM-only parameter.
        self.assertTrue(SECRET_KEY_PATTERN.search("maxTokens"))


class ScopedRuntimeConfigTests(unittest.TestCase):
    def test_secret_bearing_components_keep_config(self) -> None:
        for component in ("LiteLLM", "LLM", "ChatOllama", "AgentLoop", "HttpRequest", "ApiCaller"):
            scoped = scoped_runtime_config(component, CONFIG)
            self.assertEqual(scoped, CONFIG, component)

    def test_other_components_get_secrets_stripped(self) -> None:
        scoped = scoped_runtime_config("IfElse", CONFIG)
        self.assertNotIn("litellmApiKey", scoped)
        self.assertNotIn("authToken", scoped)
        self.assertNotIn("passwordHint", scoped)
        self.assertNotIn("secretPromptHint", scoped)
        # Non-secret config survives.
        self.assertEqual(scoped["litellmModel"], "gpt-4o-mini")
        self.assertEqual(scoped["temperature"], 0.2)
        self.assertEqual(scoped["hasOpenAIKey"], True)
        self.assertEqual(scoped["xwsAllowlist"], "s3,relay")

    def test_original_config_not_mutated(self) -> None:
        scoped_runtime_config("IfElse", CONFIG)
        self.assertEqual(CONFIG["litellmApiKey"], "sk-super-secret")

    def test_empty_and_none_configs(self) -> None:
        self.assertEqual(scoped_runtime_config("IfElse", {}), {})
        self.assertEqual(scoped_runtime_config("IfElse", None), {})
        self.assertEqual(scoped_runtime_config("LiteLLM", None), {})

    def test_bearing_set_is_frozen_and_complete(self) -> None:
        self.assertEqual(
            SECRET_BEARING_COMPONENTS,
            frozenset({"LLM", "LiteLLM", "ChatOllama", "AgentLoop", "HttpRequest", "ApiCaller"}),
        )


if __name__ == "__main__":
    unittest.main()
