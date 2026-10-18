"""Shared signing only; no visitor token is accepted as an authorization claim."""
import hashlib
import hmac
import secrets


def signed_visitor(secret: bytes, token: str | None):
    identity, _, signature = (token or "").partition(".")
    expected = hmac.new(secret, identity.encode(), "sha256").hexdigest()
    if len(identity) != 32 or not hmac.compare_digest(signature.encode(), expected.encode()):
        identity = secrets.token_hex(16)
    return identity, identity + "." + hmac.new(secret, identity.encode(), "sha256").hexdigest()
