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


_prepare_windowed_runtime()

from jarvis_papa.desktop_api_auth import install_desktop_api_auth
from jarvis_papa.onboarding import run_first_launch_onboarding

install_desktop_api_auth()

from jarvis_papa.professional_desktop_plus import run


if __name__ == "__main__":
    run_first_launch_onboarding()
    run()
