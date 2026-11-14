"""Cloudflare Turnstile server-side token verification (the browser widget alone is never trusted)."""
from __future__ import annotations

import requests

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify(token: str | None, secret: str, remote_ip: str | None = None, timeout: float = 6.0) -> tuple[bool, str]:
    """Returns (ok, reason). Never raises."""
    if not secret:
        return False, "turnstile_not_configured"
    if not token or len(token) > 2048:
        return False, "turnstile_missing"
    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        r = requests.post(VERIFY_URL, data=data, timeout=timeout)
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError):
        return False, "turnstile_unavailable"
    if body.get("success") is True:
        return True, "ok"
    return False, "turnstile_failed"
