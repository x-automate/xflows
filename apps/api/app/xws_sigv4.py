"""SigV4 verification side (stdlib port of xws_common/sigv4.py).

XFlows's API needs to *verify* inbound SigV4-signed requests from XWS
services (event triggers, docs 06 item added for XWS-originated triggers) —
the reverse direction of ``apps/workers/app/xws/sigv4.py``, which only
*signs* outgoing requests. This module ports the canonical-request
construction, string-to-sign, signature computation and freshness check
verbatim from ``xws_common.sigv4`` so verification matches the reference
implementation byte-for-byte, without depending on the ``xws-common``
package (which pulls in sqlalchemy/asyncpg/redis — irrelevant here).

Only header-auth verification is ported: XWS services sign live requests
with their own ``xws_common.service_identity.sign_headers``, never
presigned URLs, so that branch (and the chunked-streaming payload-hash
branch, irrelevant for small JSON event bodies) is omitted.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import urllib.parse
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

ALGORITHM = "AWS4-HMAC-SHA256"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: Maximum age (and forward clock skew) for a header-auth ``x-amz-date``, in
#: seconds — mirrors xws_common's replay-window enforcement (audit H1).
DEFAULT_CLOCK_SKEW = 900


def _clock_skew() -> int:
    try:
        return max(1, int(os.environ.get("XWS_SIGV4_CLOCK_SKEW", DEFAULT_CLOCK_SKEW)))
    except (TypeError, ValueError):
        return DEFAULT_CLOCK_SKEW


def enforce_freshness(amz_date: str, *, now: datetime | None = None) -> None:
    """Reject a header-auth timestamp that is stale or too far in the future."""
    if not amz_date:
        raise ValueError("MissingXAmzDate")
    try:
        amz_dt = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("InvalidXAmzDate")
    now = now or datetime.now(UTC)
    delta = (now - amz_dt).total_seconds()
    skew = _clock_skew()
    if delta > skew:
        raise ValueError("RequestTooOld")
    if delta < -skew:
        raise ValueError("RequestInFuture")


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def derive_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode(), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _canonical_uri(path: str) -> str:
    parts = path.split("/")
    encoded = [urllib.parse.quote(urllib.parse.unquote(p), safe="") for p in parts]
    return "/".join(encoded) or "/"


def _canonical_query(query_string: str) -> str:
    params = urllib.parse.parse_qsl(query_string, keep_blank_values=True)
    params.sort(key=lambda kv: kv[0])
    return urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def _canonical_headers(headers: dict[str, str], signed_headers: list[str]) -> str:
    lines = []
    for h in signed_headers:
        val = headers.get(h, "").strip()
        val = re.sub(r"\s+", " ", val)
        lines.append(f"{h}:{val}\n")
    return "".join(lines)


def build_canonical_request(
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    signed_headers: list[str],
    payload_hash: str,
) -> str:
    canon_uri = _canonical_uri(path)
    canon_query = _canonical_query(query_string)
    canon_headers = _canonical_headers(headers, signed_headers)
    signed_headers_str = ";".join(signed_headers)
    return "\n".join([
        method.upper(),
        canon_uri,
        canon_query,
        canon_headers,
        signed_headers_str,
        payload_hash,
    ])


def build_string_to_sign(canonical_request: str, amz_date: str, credential_scope: str) -> str:
    hashed_cr = hashlib.sha256(canonical_request.encode()).hexdigest()
    return "\n".join([ALGORITHM, amz_date, credential_scope, hashed_cr])


def compute_signature(
    secret_key: str, date_stamp: str, region: str, service: str, string_to_sign: str
) -> str:
    signing_key = derive_signing_key(secret_key, date_stamp, region, service)
    return hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()


def parse_auth_header(auth: str) -> dict[str, str]:
    """Returns {access_key, date_stamp, region, service, signed_headers, signature}."""
    if not auth.startswith("AWS4-HMAC-SHA256 "):
        raise ValueError("Unsupported Authorization scheme")
    parts_str = auth[len("AWS4-HMAC-SHA256 "):]
    parts: dict[str, str] = {}
    for part in parts_str.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.strip()] = v.strip()

    credential = parts.get("Credential", "")
    cred_parts = credential.split("/")
    if len(cred_parts) != 5:
        raise ValueError(f"Malformed Credential: {credential}")
    access_key, date_stamp, region, service, _req = cred_parts

    signed_headers = parts.get("SignedHeaders", "")
    signature = parts.get("Signature", "")
    if not signed_headers or not signature:
        raise ValueError("Malformed Authorization header")
    return {
        "access_key": access_key,
        "date_stamp": date_stamp,
        "region": region,
        "service": service,
        "signed_headers": signed_headers,
        "signature": signature,
    }


async def verify_request(request: "Request", secret_key: str, body: bytes) -> None:
    """Verify a header-auth SigV4 signature on an already-read request body.

    ``body`` is passed explicitly (rather than re-awaiting ``request.body()``
    as ``xws_common.sigv4.verify_request`` does) because callers here need
    the raw bytes anyway, before verification, to compute a delivery-id
    fallback hash — matching the existing HMAC webhook receiver's shape.

    Raises ValueError with a human-readable reason on failure.
    """
    method = request.method.upper()
    path = request.url.path
    query_string = request.url.query or ""
    headers_lower = {k.lower(): v for k, v in request.headers.items()}

    auth_header = headers_lower.get("authorization", "")
    if not auth_header:
        raise ValueError("MissingAuthorizationHeader")
    info = parse_auth_header(auth_header)
    amz_date = headers_lower.get("x-amz-date", "")
    enforce_freshness(amz_date)
    date_stamp = info["date_stamp"]
    region = info["region"]
    service = info["service"]
    signed_headers_list = [h.lower() for h in info["signed_headers"].split(";") if h]
    expected_sig = info["signature"]

    payload_hash_header = headers_lower.get("x-amz-content-sha256", "")
    payload_hash = payload_hash_header or EMPTY_SHA256

    canon_headers_dict = {h: headers_lower.get(h, "") for h in signed_headers_list}
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"

    canonical_request = build_canonical_request(
        method=method,
        path=path,
        query_string=query_string,
        headers=canon_headers_dict,
        signed_headers=signed_headers_list,
        payload_hash=payload_hash,
    )
    string_to_sign = build_string_to_sign(canonical_request, amz_date, credential_scope)
    computed = compute_signature(secret_key, date_stamp, region, service, string_to_sign)

    if not hmac.compare_digest(computed, expected_sig):
        raise ValueError("SignatureDoesNotMatch")

    if payload_hash_header:
        actual = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(actual, payload_hash_header.lower()):
            raise ValueError("PayloadHashMismatch")
