"""Unit tests for the ported SigV4 verification module (app.xws_sigv4)."""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta

from app.xws_sigv4 import (
    EMPTY_SHA256,
    build_canonical_request,
    build_string_to_sign,
    compute_signature,
    enforce_freshness,
    parse_auth_header,
    verify_request,
)

_REGION = "local"
_SERVICE = "xws"


class _FakeURL:
    def __init__(self, path: str, query: str = "") -> None:
        self.path = path
        self.query = query


class _FakeRequest:
    def __init__(self, method: str, path: str, headers: dict[str, str], query: str = "") -> None:
        self.method = method
        self.url = _FakeURL(path, query)
        self.headers = headers


def _sign(*, method: str, path: str, access_key: str, secret_key: str, body: bytes, amz_date: str) -> dict[str, str]:
    date_stamp = amz_date[:8]
    payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
    headers = {"x-amz-date": amz_date, "x-amz-content-sha256": payload_hash}
    signed_headers = sorted(headers.keys())
    credential_scope = f"{date_stamp}/{_REGION}/{_SERVICE}/aws4_request"
    canonical_request = build_canonical_request(
        method=method, path=path, query_string="", headers=headers,
        signed_headers=signed_headers, payload_hash=payload_hash,
    )
    string_to_sign = build_string_to_sign(canonical_request, amz_date, credential_scope)
    signature = compute_signature(secret_key, date_stamp, _REGION, _SERVICE, string_to_sign)
    return {
        "authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={';'.join(signed_headers)}, Signature={signature}"
        ),
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }


class EnforceFreshnessTests(unittest.TestCase):
    def test_valid_timestamp_accepted(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        enforce_freshness(now.strftime("%Y%m%dT%H%M%SZ"), now=now)  # no raise

    def test_missing_date_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "MissingXAmzDate"):
            enforce_freshness("")

    def test_malformed_date_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "InvalidXAmzDate"):
            enforce_freshness("not-a-date")

    def test_stale_beyond_skew_rejected(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        stale = now - timedelta(seconds=901)
        with self.assertRaisesRegex(ValueError, "RequestTooOld"):
            enforce_freshness(stale.strftime("%Y%m%dT%H%M%SZ"), now=now)

    def test_future_beyond_skew_rejected(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        future = now + timedelta(seconds=901)
        with self.assertRaisesRegex(ValueError, "RequestInFuture"):
            enforce_freshness(future.strftime("%Y%m%dT%H%M%SZ"), now=now)

    def test_within_skew_boundary_accepted(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        edge = now - timedelta(seconds=900)
        enforce_freshness(edge.strftime("%Y%m%dT%H%M%SZ"), now=now)  # no raise


class ParseAuthHeaderTests(unittest.TestCase):
    def test_valid_header_parsed(self) -> None:
        info = parse_auth_header(
            "AWS4-HMAC-SHA256 Credential=evt_abc/20260101/local/xws/aws4_request, "
            "SignedHeaders=x-amz-date;x-amz-content-sha256, Signature=deadbeef"
        )
        self.assertEqual(info["access_key"], "evt_abc")
        self.assertEqual(info["date_stamp"], "20260101")
        self.assertEqual(info["region"], "local")
        self.assertEqual(info["service"], "xws")
        self.assertEqual(info["signature"], "deadbeef")

    def test_wrong_scheme_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Authorization scheme"):
            parse_auth_header("Bearer sometoken")

    def test_malformed_credential_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Malformed Credential"):
            parse_auth_header("AWS4-HMAC-SHA256 Credential=too/few/parts, SignedHeaders=x, Signature=y")

    def test_missing_signed_headers_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Malformed Authorization header"):
            parse_auth_header(
                "AWS4-HMAC-SHA256 Credential=k/20260101/local/xws/aws4_request, Signature=y"
            )


class VerifyRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_signature_accepted(self) -> None:
        body = b'{"hello": "world"}'
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = _sign(
            method="POST", path="/events/trg_1", access_key="evt_a", secret_key="s3cr3t",
            body=body, amz_date=amz_date,
        )
        request = _FakeRequest("POST", "/events/trg_1", headers)
        await verify_request(request, "s3cr3t", body)  # no raise

    async def test_wrong_secret_rejected(self) -> None:
        body = b"{}"
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = _sign(
            method="POST", path="/events/trg_1", access_key="evt_a", secret_key="s3cr3t",
            body=body, amz_date=amz_date,
        )
        request = _FakeRequest("POST", "/events/trg_1", headers)
        with self.assertRaisesRegex(ValueError, "SignatureDoesNotMatch"):
            await verify_request(request, "wrong-secret", body)

    async def test_tampered_body_rejected(self) -> None:
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = _sign(
            method="POST", path="/events/trg_1", access_key="evt_a", secret_key="s3cr3t",
            body=b"original", amz_date=amz_date,
        )
        request = _FakeRequest("POST", "/events/trg_1", headers)
        with self.assertRaisesRegex(ValueError, "PayloadHashMismatch"):
            await verify_request(request, "s3cr3t", b"tampered")

    async def test_missing_authorization_header_rejected(self) -> None:
        request = _FakeRequest("POST", "/events/trg_1", {})
        with self.assertRaisesRegex(ValueError, "MissingAuthorizationHeader"):
            await verify_request(request, "s3cr3t", b"{}")

    async def test_stale_timestamp_rejected(self) -> None:
        body = b"{}"
        stale_date = "20200101T000000Z"
        headers = _sign(
            method="POST", path="/events/trg_1", access_key="evt_a", secret_key="s3cr3t",
            body=body, amz_date=stale_date,
        )
        request = _FakeRequest("POST", "/events/trg_1", headers)
        with self.assertRaisesRegex(ValueError, "RequestTooOld"):
            await verify_request(request, "s3cr3t", body)


if __name__ == "__main__":
    unittest.main()
