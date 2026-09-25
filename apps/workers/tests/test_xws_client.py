"""Wave 3 tests: per-run credential vending + signed XWS client.

Covers backbone fixes A11/G-5 (per-run AssumeRole, static keys rejected)
and docs 05 §4 (retry semantics) via httpx.MockTransport — no network.
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timezone

import httpx

from app.xws.client import TOOL_CLASS_ROUTES, ExponentialRetry, XWSClient
from app.xws.creds import CredentialVendor, VendedCredentials, _parse_expiration
from app.xws.errors import XWSAllowlistError, XWSCredentialError, XWSRequestError

IAM_URL = "https://iam.internal"
XWS_URL = "https://xws.internal"

ROLE_ARNS = {
    "s3": "arn:aws:iam::1234:role/xflows-s3",
    "lambda": "arn:aws:iam::1234:role/xflows-lambda",
    "relay": "arn:aws:iam::1234:role/xflows-relay",
}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _vendor_transport(calls: list[httpx.Request], expiration: float) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={
            "Credentials": {
                "AccessKeyId": "AKID-TEMP",
                "SecretAccessKey": "SECRET-TEMP",
                "SessionToken": "TOKEN",
                "Expiration": _iso(expiration),
            },
        })

    return httpx.MockTransport(handler)


def _make_vendor(
    calls: list[httpx.Request] | None = None,
    expiration: float | None = None,
) -> CredentialVendor:
    calls = calls if calls is not None else []
    expiry = expiration if expiration is not None else time.time() + 3600
    return CredentialVendor(
        iam_endpoint=IAM_URL,
        access_key_id="AKID-STATIC",
        secret_access_key="SECRET-STATIC",
        region="us-east-1",
        role_arns=ROLE_ARNS,
        transport=_vendor_transport(calls, expiry),
    )


class CredentialVendorTests(unittest.TestCase):
    def test_assume_role_request_shape(self) -> None:
        calls: list[httpx.Request] = []
        vendor = _make_vendor(calls)
        creds = vendor.get_credentials("run_1", "s3")

        self.assertEqual(creds.access_key_id, "AKID-TEMP")
        self.assertEqual(creds.session_token, "TOKEN")
        self.assertEqual(creds.role_arn, ROLE_ARNS["s3"])
        self.assertEqual(creds.tool_class, "s3")

        request = calls[0]
        body = json.loads(request.content)
        self.assertTrue(request.url.path.startswith("/iam/assume-role"))
        self.assertEqual(body["RoleArn"], ROLE_ARNS["s3"])
        self.assertTrue(body["RoleSessionName"].startswith("xflows-run_1"))
        tags = {t["Key"]: t["Value"] for t in body["Tags"]}
        self.assertEqual(tags["xws-project"], "apigen")
        self.assertEqual(tags["xflows-run-id"], "run_1")
        self.assertEqual(request.headers["x-xws-project"], "apigen")
        self.assertIn("AKID-STATIC", request.headers["Authorization"])

    def test_credentials_are_cached_per_run_and_tool_class(self) -> None:
        calls: list[httpx.Request] = []
        vendor = _make_vendor(calls)
        vendor.get_credentials("run_1", "s3")
        vendor.get_credentials("run_1", "s3")
        self.assertEqual(len(calls), 1)

    def test_short_expiry_triggers_refresh(self) -> None:
        calls: list[httpx.Request] = []
        vendor = _make_vendor(calls, expiration=time.time() + 60)
        vendor.get_credentials("run_1", "s3")
        vendor.get_credentials("run_1", "s3")
        self.assertEqual(len(calls), 2)

    def test_unknown_tool_class_fails_closed_without_http(self) -> None:
        calls: list[httpx.Request] = []
        vendor = _make_vendor(calls)
        with self.assertRaises(XWSCredentialError) as ctx:
            vendor.get_credentials("run_1", "nope")
        self.assertIn("nope", str(ctx.exception))
        self.assertEqual(calls, [])

    def test_iam_500_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        vendor = CredentialVendor(
            iam_endpoint=IAM_URL,
            access_key_id="AKID-STATIC",
            secret_access_key="SECRET-STATIC",
            region="us-east-1",
            role_arns=ROLE_ARNS,
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(XWSCredentialError) as ctx:
            vendor.get_credentials("run_1", "s3")
        self.assertIn("500", str(ctx.exception))

    def test_parse_expiration(self) -> None:
        self.assertEqual(_parse_expiration(1234.5), 1234.5)
        self.assertEqual(_parse_expiration("1234.5"), 1234.5)
        parsed = _parse_expiration("2026-09-22T00:00:00Z")
        self.assertAlmostEqual(parsed, datetime(2026, 9, 22, tzinfo=timezone.utc).timestamp(), delta=1)
        with self.assertRaises(XWSCredentialError):
            _parse_expiration("not-a-date")


class ClientAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = XWSClient(base_url=XWS_URL, region="us-east-1")

    def test_method_outside_tool_class_is_denied(self) -> None:
        with self.assertRaises(XWSAllowlistError):
            self.client.request(
                method="PUT", path="/iam/evaluate", tool_class="s3", run_id="run_1",
            )

    def test_unknown_tool_class_is_denied(self) -> None:
        with self.assertRaises(XWSAllowlistError):
            self.client.request(
                method="GET", path="/s3/b/k", tool_class="mystery", run_id="run_1",
            )

    def test_route_table_shape(self) -> None:
        self.assertIn(("POST", "/lambda/invoke"), TOOL_CLASS_ROUTES["lambda"])
        self.assertIn(("GET", "/dms/"), TOOL_CLASS_ROUTES["dms-ro"])
        self.assertIn(("POST", "/relay/notify"), TOOL_CLASS_ROUTES["relay"])
        # audit-svc's real route is /events/append — /audit/append never existed there.
        self.assertIn(("POST", "/events/append"), TOOL_CLASS_ROUTES["audit"])


class ClientSignedRequestTests(unittest.TestCase):
    def test_request_is_signed_with_vended_creds(self) -> None:
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json={"ok": True})

        client = XWSClient(
            base_url=XWS_URL,
            region="us-east-1",
            vendor=_make_vendor(),
            transport=httpx.MockTransport(handler),
        )
        result = client.request(
            method="POST",
            path="/lambda/invoke/render",
            tool_class="lambda",
            run_id="run_1",
            json_body={"payload": {"x": 1}},
            idempotency_key="bundle-abc123",
        )

        self.assertEqual(result, {"ok": True})
        request = sent[0]
        self.assertEqual(request.headers["X-Amz-Security-Token"], "TOKEN")
        self.assertIn("AKID-TEMP", request.headers["Authorization"])
        self.assertIn("aws4_request", request.headers["Authorization"])
        self.assertEqual(request.headers["x-xws-project"], "apigen")
        self.assertEqual(request.headers["Idempotency-Key"], "bundle-abc123")
        self.assertEqual(request.headers["Content-Type"], "application/json")
        body = json.loads(request.content)
        self.assertEqual(body, {"payload": {"x": 1}})

    def test_500_is_retried_then_succeeds(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(500, text="transient")
            return httpx.Response(200, json={"ok": True})

        client = XWSClient(
            base_url=XWS_URL,
            region="us-east-1",
            vendor=_make_vendor(),
            transport=httpx.MockTransport(handler),
            retry=ExponentialRetry(max_attempts=3, base_delay=0.001),
        )
        result = client.request(
            method="POST", path="/relay/notify", tool_class="relay", run_id="run_1",
            json_body={"message": "m"}, retry=True,
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)

    def test_400_is_not_retried(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(400, text="bad request")

        client = XWSClient(
            base_url=XWS_URL,
            region="us-east-1",
            vendor=_make_vendor(),
            transport=httpx.MockTransport(handler),
            retry=ExponentialRetry(max_attempts=3, base_delay=0.001),
        )
        with self.assertRaises(XWSRequestError) as ctx:
            client.request(
                method="POST", path="/relay/notify", tool_class="relay", run_id="run_1",
                json_body={"message": "m"}, retry=True,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(len(calls), 1)

    def test_transport_error_maps_to_503(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        client = XWSClient(
            base_url=XWS_URL,
            region="us-east-1",
            vendor=_make_vendor(),
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(XWSRequestError) as ctx:
            client.request(
                method="GET", path="/s3/b/k", tool_class="s3", run_id="run_1",
            )
        self.assertEqual(ctx.exception.status_code, 503)

    def test_204_returns_empty_dict(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        client = XWSClient(
            base_url=XWS_URL,
            region="us-east-1",
            vendor=_make_vendor(),
            transport=httpx.MockTransport(handler),
        )
        result = client.request(
            method="PUT", path="/s3/bucket/key.txt", tool_class="s3", run_id="run_1",
            json_body={"body": "x"},
        )
        self.assertEqual(result, {})


class ExponentialRetryTests(unittest.TestCase):
    def test_backoff_doubles(self) -> None:
        policy = ExponentialRetry(max_attempts=3, base_delay=0.001)
        self.assertEqual(policy.attempts(), 3)
        self.assertEqual(policy.backoff_seconds(1), 0.001)
        self.assertEqual(policy.backoff_seconds(2), 0.002)
        self.assertEqual(policy.backoff_seconds(3), 0.004)


class VendedCredentialsTests(unittest.TestCase):
    def test_expires_in_is_relative_to_now(self) -> None:
        creds = VendedCredentials(
            access_key_id="a",
            secret_access_key="s",
            session_token="t",
            expiration=time.time() + 100,
            role_arn="arn:x",
            tool_class="s3",
        )
        self.assertTrue(90 < creds.expires_in <= 100)


class BuildXwsClientWiringTests(unittest.TestCase):
    """activities._build_xws_client must vend per-run clients with a retry policy."""

    def setUp(self) -> None:
        from app import activities

        self.activities = activities
        self._original_clients = dict(activities._XWS_CLIENTS)
        self._original_settings = activities.settings
        activities._XWS_CLIENTS.clear()

    def tearDown(self) -> None:
        self.activities._XWS_CLIENTS.clear()
        self.activities._XWS_CLIENTS.update(self._original_clients)
        self.activities.settings = self._original_settings

    def _ready_settings(self):
        from app.config import Settings

        return Settings(
            xws_enabled=True,
            xws_base_url=XWS_URL,
            xws_iam_endpoint=IAM_URL,
            xws_access_key_id="AKID-STATIC",
            xws_secret_access_key="SECRET-STATIC",
            xws_role_arns="s3=arn:aws:iam::1234:role/xflows-s3",
        )

    def test_not_configured_returns_none(self) -> None:
        from app.config import Settings

        self.activities.settings = Settings(xws_enabled=False)
        self.assertIsNone(self.activities._build_xws_client("run_1"))

    def test_ready_settings_build_cached_client_with_retry(self) -> None:
        self.activities.settings = self._ready_settings()
        client = self.activities._build_xws_client("run_1")
        self.assertIsNotNone(client)
        self.assertIsInstance(client._retry, ExponentialRetry)
        self.assertEqual(client._retry.attempts(), 5)
        # Same run id reuses the cached client.
        self.assertIs(self.activities._build_xws_client("run_1"), client)
        self.assertEqual(list(self.activities._XWS_CLIENTS), ["run_1"])


if __name__ == "__main__":
    unittest.main()
