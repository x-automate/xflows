"""SigV4 signing side (stdlib port of xws_common/sigv4.py).

XFlows only ever *signs* outgoing XWS requests; verification lives in
``xws_common.sigv4`` inside each service. This module ports the
canonical-request construction, string-to-sign and signature computation
verbatim so signatures match the reference implementation byte-for-byte,
and adds temporary-credential support (``X-Amz-Security-Token``) required
by per-run STS vended credentials (backbone fix G-5).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import urllib.parse
from datetime import UTC, datetime

ALGORITHM = "AWS4-HMAC-SHA256"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def derive_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode(), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _canonical_uri(path: str) -> str:
    """Double-encode each path segment (S3 path encoding)."""
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


def build_string_to_sign(
    canonical_request: str,
    amz_date: str,
    credential_scope: str,
) -> str:
    hashed_cr = hashlib.sha256(canonical_request.encode()).hexdigest()
    return "\n".join([ALGORITHM, amz_date, credential_scope, hashed_cr])


def compute_signature(
    secret_key: str,
    date_stamp: str,
    region: str,
    service: str,
    string_to_sign: str,
) -> str:
    signing_key = derive_signing_key(secret_key, date_stamp, region, service)
    return hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()


def sign_request(
    *,
    method: str,
    url: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    body: bytes = b"",
    session_token: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return SigV4 headers for an outgoing XWS request.

    Mirrors ``xws_common.service_identity.sign_headers`` (path signed decoded,
    so FastAPI's decoded ``request.url.path`` matches on verification) and
    adds ``X-Amz-Security-Token`` for STS vended credentials (G-5).
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    path = urllib.parse.unquote(parsed.path or "/")
    query = parsed.query or ""

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256

    headers = {
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }
    if session_token:
        headers["x-amz-security-token"] = session_token
    if extra_headers:
        headers.update({k.lower(): v for k, v in extra_headers.items()})

    signed_headers = sorted(headers.keys())
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"

    canonical_request = build_canonical_request(
        method=method.upper(), path=path, query_string=query,
        headers=headers, signed_headers=signed_headers, payload_hash=payload_hash,
    )
    string_to_sign = build_string_to_sign(canonical_request, amz_date, credential_scope)
    signature = compute_signature(secret_key, date_stamp, region, service, string_to_sign)

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={';'.join(signed_headers)}, Signature={signature}"
    )
    out = {
        "Authorization": authorization,
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
    }
    if session_token:
        out["X-Amz-Security-Token"] = session_token
    if extra_headers:
        out.update(extra_headers)
    return out
