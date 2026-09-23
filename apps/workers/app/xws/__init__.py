"""XWS integration layer for XFlows workers.

Implements Wave 3 of the APIGen/XFlows upgrade plan:
  - sigv4.SigningHeaders: stdlib signing side of xws_common/sigv4.py
  - client.XWSClient: SigV4-signed HTTP client for XWS tool endpoints
  - creds.CredentialVendor: per-run STS AssumeRole credential vending (G-5)
"""

from .client import ExponentialRetry, XWSClient
from .creds import CredentialVendor, VendedCredentials
from .errors import (
    XWSAllowlistError,
    XWSCredentialError,
    XWSError,
    XWSRequestError,
    XWSSignatureError,
)

__all__ = [
    "XWSClient",
    "ExponentialRetry",
    "XWSError",
    "XWSRequestError",
    "XWSSignatureError",
    "XWSCredentialError",
    "XWSAllowlistError",
    "CredentialVendor",
    "VendedCredentials",
]
