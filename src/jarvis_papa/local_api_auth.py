from __future__ import annotations

import os
import secrets
import sys

from jarvis_papa.config import settings
from jarvis_papa.secret_store import windows_secret_store

_TOKEN_ENV = "JARVIS_LOCAL_API_TOKEN"
_TOKEN_NAME = "local_api_auth_token"


def installed_windows() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def local_api_token() -> str:
    """Return the shared local-API token without ever using a plaintext fallback.

    Source/developer mode deliberately leaves authentication disabled unless an
    explicit environment token is supplied. Installed Windows builds fail closed:
    the token is generated once and stored with current-user DPAPI protection.
    """

    environment = os.environ.get(_TOKEN_ENV, "").strip()
    if environment:
        return environment
    if not installed_windows():
        return ""

    data_dir = settings.runtime_dir.parent
    store = windows_secret_store(data_dir)
    if store is None:
        raise RuntimeError("Le stockage sécurisé Windows de Jarvis est indisponible.")

    token = store.get(_TOKEN_NAME).strip()
    if token:
        return token

    store.set(_TOKEN_NAME, secrets.token_urlsafe(48))
    verified = store.get(_TOKEN_NAME).strip()
    if not verified:
        raise RuntimeError("Jarvis n'a pas pu protéger son jeton API local.")
    return verified


def api_auth_headers(client_name: str = "jarvis") -> dict[str, str]:
    token = local_api_token()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "X-Jarvis-Client": client_name.strip()[:80] or "jarvis",
    }
