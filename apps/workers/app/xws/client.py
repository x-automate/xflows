"""SigV4-signed HTTP client for XWS tool endpoints.

``XWSClient`` is the single place where XFlows talks to XWS services.
It signs every request inline (no static auth headers), pins the
``x-xws-project`` header, and enforces the per-run allowlist:
a node may only reach endpoints belonging to its declared toolClass.
Transport injection mirrors ``provider_router`` so tests can pass an
``httpx.MockTransport`` without any network access.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from typing import Any, Protocol

import httpx

from .creds import CredentialVendor
from .errors import (
    XWSAllowlistError,
    XWSCredentialError,
    XWSError,
    XWSRequestError,
    XWSSignatureError,
)
from .sigv4 import sign_request

logger = logging.getLogger(__name__)

# toolClass -> set of allowed (method, path-prefix) pairs. Runtime half of
# the allowlist enforcement; authoring-time half lives in the catalog.
TOOL_CLASS_ROUTES: dict[str, tuple[tuple[str, str], ...]] = {
    "s3": (("PUT", "/s3/"), ("GET", "/s3/"), ("POST", "/s3/")),
    "lambda": (("POST", "/lambda/invoke"),),
    "iam": (("POST", "/iam/evaluate"),),
    "relay": (("POST", "/relay/notify"),),
    "audit": (("POST", "/events/append"),),
    "dms-ro": (("GET", "/dms/"),),
    "apigw": (("POST", "/apigw/"), ("DELETE", "/apigw/")),
    "llm": (("POST", "/llm/"),),
}


# Error classes live in errors.py; re-exported here for backwards
# compatibility with ``from .client import XWSError`` style imports.
__all__ = [
    "TOOL_CLASS_ROUTES",
    "XWSAllowlistError",
    "XWSCredentialError",
    "XWSClient",
    "XWSError",
    "XWSRequestError",
    "XWSSignatureError",
]


class RetryPolicy(Protocol):
    def attempts(self) -> int: ...
    def backoff_seconds(self, attempt: int) -> float: ...


class ExponentialRetry:
    """docs 05 §4: S3 artifacts retry 5x with exponential backoff."""

    def __init__(self, max_attempts: int = 5, base_delay: float = 0.2) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay

    def attempts(self) -> int:
        return self.max_attempts

    def backoff_seconds(self, attempt: int) -> float:
        return self.base_delay * (2 ** (attempt - 1))


class XWSClient:
    """Signs and sends requests to XWS services with per-run vended creds."""

    def __init__(
        self,
        *,
        base_url: str,
        region: str,
        service: str = "execute-api",
        vendor: CredentialVendor | None = None,
        transport: httpx.BaseTransport | None = None,
        retry: ExponentialRetry | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._region = region
        self._service = service
        self._vendor = vendor
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._client = httpx.Client(transport=transport, timeout=timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    def request(
        self,
        *,
        method: str,
        path: str,
        tool_class: str,
        run_id: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        idempotency_key: str | None = None,
        retry: bool = False,
    ) -> dict[str, Any]:
        """Perform a signed XWS request and return the parsed JSON body."""
        self._check_allowlist(method, path, tool_class)

        creds = None
        if self._vendor is not None:
            creds = self._vendor.get_credentials(run_id, tool_class)

        body_bytes = b""
        headers: dict[str, str] = {
            "x-xws-project": "apigen",
            "accept": "application/json",
        }
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode()
            headers["content-type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        extra = dict(headers)

        attempts = self._retry.attempts() if (retry and self._retry) else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            auth_headers = sign_request(
                method=method,
                url=self._build_url(path, params),
                access_key=creds.access_key_id if creds else "UNSIGNED",
                secret_key=creds.secret_access_key if creds else "UNSIGNED",
                region=self._region,
                service=self._service,
                body=body_bytes,
                session_token=creds.session_token if creds else None,
                extra_headers=extra,
            )
            try:
                response = self._client.request(
                    method,
                    self._build_url(path, params),
                    content=body_bytes if body_bytes else None,
                    headers=auth_headers,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(self._retry.backoff_seconds(attempt))
                    continue
                raise XWSRequestError(503, f"transport error: {exc}") from exc
            if response.status_code >= 500 and attempt < attempts:
                last_error = XWSRequestError(response.status_code, response.text)
                time.sleep(self._retry.backoff_seconds(attempt))
                continue
            if response.status_code >= 400:
                raise XWSRequestError(response.status_code, response.text)
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()
        raise XWSRequestError(500, f"retry loop exited unexpectedly: {last_error}")

    def _build_url(self, path: str, params: dict[str, str] | None) -> str:
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return url

    @staticmethod
    def _check_allowlist(method: str, path: str, tool_class: str) -> None:
        routes = TOOL_CLASS_ROUTES.get(tool_class)
        if routes is None:
            raise XWSAllowlistError(f"unknown toolClass {tool_class!r}")
        upper = method.upper()
        for allowed_method, prefix in routes:
            if upper == allowed_method and path.startswith(prefix):
                return
        raise XWSAllowlistError(
            f"toolClass {tool_class!r} is not allowed to call "
            f"{upper} {path} (allowlist: {routes})"
        )
