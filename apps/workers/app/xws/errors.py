"""Error taxonomy for the XWS integration layer.

Lives in its own module so ``client.py`` and ``creds.py`` can share it
without a circular import.
"""

from __future__ import annotations


class XWSError(Exception):
    """Base error for XWS client failures."""


class XWSSignatureError(XWSError):
    """Signing inputs were invalid."""


class XWSCredentialError(XWSError):
    """Credential vending (AssumeRole) failed — fail closed."""


class XWSAllowlistError(XWSError):
    """Requested route is not in the toolClass allowlist."""


class XWSRequestError(XWSError):
    """XWS service returned a non-success response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"XWS returned HTTP {status_code}: {body[:200]}")
