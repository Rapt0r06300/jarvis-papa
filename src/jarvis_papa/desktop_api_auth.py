from __future__ import annotations

from typing import Any

import httpx

from jarvis_papa.local_api_auth import api_auth_headers


def install_desktop_api_auth() -> None:
    """Patch the shared desktop ApiClient before the production window imports it."""

    from jarvis_papa import desktop_app

    def secure_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        timeout: float = 12.0,
    ) -> Any:
        headers = api_auth_headers("jarvis-desktop")
        with httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
        ) as client:
            response = client.request(method, path, json=payload, params=params)
            response.raise_for_status()
            return response.json()

    desktop_app.ApiClient.request = secure_request
