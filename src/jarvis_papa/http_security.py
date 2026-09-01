from __future__ import annotations

import ipaddress
import secrets
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jarvis_papa.local_api_auth import local_api_token

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
_ALLOWED_TEST_CLIENTS = {"testclient"}
_PUBLIC_LOCAL_PATHS = {
    "/",
    "/health",
    "/api/status",
    "/api/advanced/voice/quality",
    "/openapi.json",
}


def _hostname(value: str) -> str:
    if not value:
        return ""
    try:
        return (urlparse(value).hostname or "").casefold()
    except ValueError:
        return ""


def _host_header_name(value: str) -> str:
    try:
        return (urlparse(f"//{value}").hostname or "").casefold()
    except ValueError:
        return ""


def _is_loopback_client(host: str) -> bool:
    if host in _ALLOWED_TEST_CLIENTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.casefold() == "localhost"


def _authorized(request: Request, expected: str) -> bool:
    if not expected:
        return True
    value = request.headers.get("authorization", "")
    scheme, _, supplied = value.partition(" ")
    return (
        scheme.casefold() == "bearer"
        and bool(supplied)
        and secrets.compare_digest(supplied.strip(), expected)
    )


def install_http_security(app: FastAPI) -> None:
    @app.middleware("http")
    async def local_only_guard(request: Request, call_next):
        host = _host_header_name(request.headers.get("host", ""))
        client_host = request.client.host if request.client else ""
        if host not in _ALLOWED_HOSTS or not _is_loopback_client(client_host):
            return JSONResponse(
                status_code=403,
                content={"detail": "Jarvis accepte uniquement les connexions locales."},
            )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin", "")
            if origin and _hostname(origin) not in _ALLOWED_HOSTS:
                return JSONResponse(status_code=403, content={"detail": "Origine web refusée."})
            referer = request.headers.get("referer", "")
            if referer and _hostname(referer) not in _ALLOWED_HOSTS:
                return JSONResponse(status_code=403, content={"detail": "Référent web refusé."})

        try:
            expected_token = local_api_token()
        except (OSError, RuntimeError, ValueError):
            return JSONResponse(
                status_code=503,
                content={"detail": "La protection locale de Jarvis est indisponible."},
            )
        if request.url.path not in _PUBLIC_LOCAL_PATHS and not _authorized(
            request, expected_token
        ):
            return JSONResponse(
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                content={"detail": "Client Jarvis local non authentifié."},
            )

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
