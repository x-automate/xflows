"""Per-run STS credential vending (backbone fixes A11 + G-5).

XFlows never holds static service credentials for XWS calls. Instead,
for every (run, toolClass) pair it performs an STS ``AssumeRole`` against
iam-svc and uses the resulting *temporary* credentials — which carry an
``x-amz-security-token`` session token — to sign SigV4 requests. XWS
services validate that token's provenance and claims (fix G-5), so
static/long-lived keys are rejected by design.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from .errors import XWSCredentialError
from .sigv4 import sign_request

logger = logging.getLogger(__name__)

_EXPIRY_MARGIN_S = 120  # refresh this long before real expiry


@dataclass(slots=True)
class VendedCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: float  # unix epoch seconds
    role_arn: str
    tool_class: str

    @property
    def expires_in(self) -> float:
        return self.expiration - time.time()


class CredentialVendor:
    """Vends per-run, per-toolClass STS credentials via iam-svc.

    ``tool_class_role_arns`` maps a toolClass (e.g. ``"s3"``, ``"lambda"``)
    to the least-privilege role ARN XFlows should assume for that class
    (docs 05 §2 permission matrix). Cache is keyed by ``(run_id, tool_class)``
    so one workflow run reuses one credential set per tool class.
    """

    def __init__(
        self,
        *,
        iam_endpoint: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        service: str = "execute-api",
        role_arns: dict[str, str],
        session_duration_s: int = 900,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._iam_endpoint = iam_endpoint.rstrip("/")
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region
        self._service = service
        self._role_arns = dict(role_arns)
        self._session_duration_s = session_duration_s
        self._transport = transport
        self._client = httpx.Client(transport=transport, timeout=10.0)
        self._cache: dict[tuple[str, str], VendedCredentials] = {}

    def role_arn_for(self, tool_class: str) -> str:
        try:
            return self._role_arns[tool_class]
        except KeyError:
            raise XWSCredentialError(
                f"no IAM role configured for toolClass {tool_class!r}; "
                f"known classes: {sorted(self._role_arns)}"
            ) from None

    def get_credentials(self, run_id: str, tool_class: str) -> VendedCredentials:
        key = (run_id, tool_class)
        cached = self._cache.get(key)
        if cached and cached.expires_in > _EXPIRY_MARGIN_S:
            return cached
        creds = self._assume_role(run_id, tool_class)
        self._cache[key] = creds
        return creds

    def invalidate(self, run_id: str, tool_class: str | None = None) -> None:
        if tool_class is None:
            for key in [k for k in self._cache if k[0] == run_id]:
                del self._cache[key]
        else:
            self._cache.pop((run_id, tool_class), None)

    def _assume_role(self, run_id: str, tool_class: str) -> VendedCredentials:
        role_arn = self.role_arn_for(tool_class)
        body = json.dumps({
            "RoleArn": role_arn,
            "RoleSessionName": f"xflows-{run_id}"[:64],
            "DurationSeconds": self._session_duration_s,
            "Tags": [
                {"Key": "xws-project", "Value": "apigen"},
                {"Key": "xflows-run-id", "Value": run_id},
            ],
        }).encode()

        url = f"{self._iam_endpoint}/iam/assume-role"
        auth_headers = sign_request(
            method="POST",
            url=url,
            access_key=self._access_key_id,
            secret_key=self._secret_key_bytes(),
            region=self._region,
            service=self._service,
            body=body,
            extra_headers={"content-type": "application/json", "x-xws-project": "apigen"},
        )
        try:
            response = self._client.post(
                url,
                content=body,
                headers=auth_headers,
            )
        except httpx.HTTPError as exc:
            raise XWSCredentialError(
                f"AssumeRole request to iam-svc failed for toolClass {tool_class!r}: {exc}"
            ) from exc
        if response.status_code != 200:
            # Fail closed: no credentials means the tool call cannot proceed.
            raise XWSCredentialError(
                f"AssumeRole for toolClass {tool_class!r} returned "
                f"HTTP {response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
        creds_block = payload.get("Credentials") or payload
        try:
            access_key = creds_block["AccessKeyId"]
            secret_key = creds_block["SecretAccessKey"]
            session_token = creds_block["SessionToken"]
            expiration = creds_block["Expiration"]
        except (KeyError, TypeError) as exc:
            raise XWSCredentialError(
                f"iam-svc AssumeRole response missing fields for toolClass {tool_class!r}"
            ) from exc
        expiry_epoch = _parse_expiration(expiration)
        logger.info(
            "vended %s credentials for run=%s toolClass=%s role=%s",
            tool_class, run_id, tool_class, role_arn,
        )
        return VendedCredentials(
            access_key_id=access_key,
            secret_access_key=secret_key,
            session_token=session_token,
            expiration=expiry_epoch,
            role_arn=role_arn,
            tool_class=tool_class,
        )

    def _secret_key_bytes(self) -> str:
        # sign_request expects the secret as str; kept as helper for clarity.
        return self._secret_access_key


def _parse_expiration(raw: object) -> float:
    """Accept ISO-8601 strings or numeric epochs from iam-svc."""
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    try:
        return float(text)
    except ValueError:
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.timestamp()
    except ValueError:
        raise XWSCredentialError(f"unparseable credential expiration: {raw!r}") from None
