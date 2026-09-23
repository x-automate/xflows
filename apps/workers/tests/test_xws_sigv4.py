"""Wave 3 tests: SigV4 signing (docs 05 §7, backbone fix G-5).

Golden vectors were computed with an independent raw hmac/hashlib script
(``sigv4_golden.py``) so these tests do not merely re-run the
implementation against itself.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from app.xws import sigv4

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
DATE_STAMP = "20260922"
REGION = "us-east-1"
SERVICE = "execute-api"

# Independent KAT for the signing-key derivation chain.
KEY_HEX = "a2704a64bc16f34a3b0bf9b5f5eb92c2c3a6a60a1af372ed0334eddce7478f48"

GOLDEN_URL = "https://xws.internal/s3/apigen-artifacts/runs/a.txt"
GOLDEN_BODY = b'{"body":"hello"}'
GOLDEN_PAYLOAD_HASH = (
    "1da63ae1d1c64f4549cece58555b23ef253aa7bb2c5ca6c48c12918863cff51a"
)
GOLDEN_SIGNED_HEADERS = (
    "content-type;host;x-amz-content-sha256;x-amz-date;"
    "x-amz-security-token;x-xws-project"
)
GOLDEN_SIGNATURE = (
    "b12a732789bbdcc85ccf71ab1a1fadd001d419a9c14cd74a97c996a61aefbfea"
)
GOLDEN_CR_SHA = (
    "a7bc4f4b1e79b2d0e3e856793d652a4c71482f42339816895d1dce3e675012c0"
)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ARG003
        return datetime(2026, 9, 22, 0, 0, 0, tzinfo=timezone.utc)


class DeriveSigningKeyTests(unittest.TestCase):
    def test_known_answer_vector(self) -> None:
        key = sigv4.derive_signing_key(SECRET, DATE_STAMP, REGION, SERVICE)
        self.assertEqual(key.hex(), KEY_HEX)


class CanonicalRequestTests(unittest.TestCase):
    def test_plain_path_is_unchanged(self) -> None:
        self.assertEqual(sigv4._canonical_uri("/s3/bucket/key.txt"), "/s3/bucket/key.txt")

    def test_special_chars_are_encoded(self) -> None:
        # Segments are signed decoded, then re-encoded once (see sign_request).
        self.assertEqual(sigv4._canonical_uri("/a b/c"), "/a%20b/c")

    def test_encoding_is_idempotent(self) -> None:
        # An already-encoded path normalizes back to the same canonical form.
        self.assertEqual(sigv4._canonical_uri("/a%20b/c"), "/a%20b/c")

    def test_empty_path_becomes_root(self) -> None:
        self.assertEqual(sigv4._canonical_uri(""), "/")

    def test_query_is_sorted_by_key_with_blank_values_kept(self) -> None:
        # Sort is by key only; duplicate keys keep their original order.
        self.assertEqual(
            sigv4._canonical_query("b=2&a=1&a=0&c="),
            "a=1&a=0&b=2&c=",
        )

    def test_empty_query_stays_empty(self) -> None:
        self.assertEqual(sigv4._canonical_query(""), "")


class SignRequestTests(unittest.TestCase):
    def test_golden_vector(self) -> None:
        with mock.patch("app.xws.sigv4.datetime", _FrozenDatetime):
            headers = sigv4.sign_request(
                method="POST",
                url=GOLDEN_URL,
                access_key="AKIDEXAMPLE",
                secret_key=SECRET,
                region=REGION,
                service=SERVICE,
                body=GOLDEN_BODY,
                session_token="TOKEN123",
                extra_headers={
                    "content-type": "application/json",
                    "x-xws-project": "apigen",
                },
            )
        self.assertEqual(headers["X-Amz-Date"], "20260922T000000Z")
        self.assertEqual(headers["X-Amz-Content-Sha256"], GOLDEN_PAYLOAD_HASH)
        self.assertEqual(headers["X-Amz-Security-Token"], "TOKEN123")
        self.assertEqual(headers["x-xws-project"], "apigen")
        auth = headers["Authorization"]
        self.assertIn(
            "Credential=AKIDEXAMPLE/20260922/us-east-1/execute-api/aws4_request",
            auth,
        )
        self.assertIn(f"SignedHeaders={GOLDEN_SIGNED_HEADERS}", auth)
        self.assertIn(f"Signature={GOLDEN_SIGNATURE}", auth)

    def test_canonical_request_hash_matches_golden(self) -> None:
        headers = {
            "host": "xws.internal",
            "x-amz-date": "20260922T000000Z",
            "x-amz-content-sha256": GOLDEN_PAYLOAD_HASH,
            "x-amz-security-token": "TOKEN123",
            "content-type": "application/json",
            "x-xws-project": "apigen",
        }
        signed = sorted(headers.keys())
        cr = sigv4.build_canonical_request(
            method="POST",
            path="/s3/apigen-artifacts/runs/a.txt",
            query_string="",
            headers=headers,
            signed_headers=signed,
            payload_hash=GOLDEN_PAYLOAD_HASH,
        )
        import hashlib

        self.assertEqual(hashlib.sha256(cr.encode()).hexdigest(), GOLDEN_CR_SHA)
        self.assertEqual(";".join(signed), GOLDEN_SIGNED_HEADERS)

    def test_empty_body_uses_empty_sha256(self) -> None:
        with mock.patch("app.xws.sigv4.datetime", _FrozenDatetime):
            headers = sigv4.sign_request(
                method="GET",
                url="https://xws.internal/s3/bucket/k",
                access_key="AKIDEXAMPLE",
                secret_key=SECRET,
                region=REGION,
                service=SERVICE,
            )
        self.assertEqual(
            headers["X-Amz-Content-Sha256"],
            sigv4.EMPTY_SHA256,
        )


class StringToSignTests(unittest.TestCase):
    def test_shape(self) -> None:
        sts = sigv4.build_string_to_sign("cr", "20260922T000000Z", f"{DATE_STAMP}/{REGION}/{SERVICE}/aws4_request")
        lines = sts.split("\n")
        self.assertEqual(lines[0], sigv4.ALGORITHM)
        self.assertEqual(lines[1], "20260922T000000Z")
        self.assertEqual(lines[2], "20260922/us-east-1/execute-api/aws4_request")
        self.assertEqual(len(lines[3]), 64)


if __name__ == "__main__":
    unittest.main()
