from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_windowed_runtime() -> None:
    """PyInstaller windowed apps have no console streams; libraries may still require them."""

    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    runtime = root / "JarvisPapa" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    log = (runtime / "jarvis-desktop.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def _bundle_uvicorn_runtime_modules() -> None:
    """Make Uvicorn's dynamically selected runtime modules visible to PyInstaller."""

    if not getattr(sys, "frozen", False):
        return
    from uvicorn.lifespan import on as uvicorn_lifespan_on
    from uvicorn.loops import auto as uvicorn_loop_auto
    from uvicorn.protocols.http import auto as uvicorn_http_auto
    from uvicorn.protocols.websockets import auto as uvicorn_websocket_auto

    _ = (
        uvicorn_lifespan_on,
        uvicorn_loop_auto,
        uvicorn_http_auto,
        uvicorn_websocket_auto,
    )


def _set_windows_app_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JarvisPapa.Desktop")
    except (AttributeError, OSError):
        return


_prepare_windowed_runtime()
_bundle_uvicorn_runtime_modules()
_set_windows_app_identity()

from jarvis_papa.restore_coordinator import restore_coordinator

_restore_result = restore_coordinator.apply_pending()
if not _restore_result.get("ok"):
    print(f"Jarvis restore warning: {_restore_result.get('detail')}", file=sys.stderr)

from jarvis_papa.desktop_api_auth import install_desktop_api_auth
from jarvis_papa.onboarding import run_first_launch_onboarding

install_desktop_api_auth()

from jarvis_papa.activity_desktop import run


if __name__ == "__main__":
    run_first_launch_onboarding()
    run()
