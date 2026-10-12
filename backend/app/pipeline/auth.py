"""Verify the OIDC token Pub/Sub attaches to push requests."""
from __future__ import annotations

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import get_settings


class PushAuthError(Exception):
    pass


def verify_push_request(auth_header: str | None) -> dict:
    """Check the signature, audience, expiry (via google-auth), then the caller identity.
    Fails closed when the audience or expected identity is not configured."""
    s = get_settings()
    if not s.worker_audience or not s.push_invoker_email:
        raise PushAuthError("worker auth is not configured")
    scheme, _, token = (auth_header or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise PushAuthError("missing bearer token")
    try:
        claims = id_token.verify_oauth2_token(token, google_requests.Request(), audience=s.worker_audience)
    except Exception as err:  # noqa: BLE001
        raise PushAuthError(f"invalid token: {type(err).__name__}") from err
    if claims.get("email") != s.push_invoker_email or not claims.get("email_verified"):
        raise PushAuthError("unexpected caller identity")
    return claims
