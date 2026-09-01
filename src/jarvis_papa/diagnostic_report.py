from __future__ import annotations

import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from jarvis_papa import __version__
from jarvis_papa.config import settings
from jarvis_papa.diagnostics import diagnostics
from jarvis_papa.memory import memory_store

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "cvv",
    "pin",
}
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{10,}\b", re.IGNORECASE),
)


def _safe_string(value: str) -> str:
    text = value
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    home = str(Path.home())
    if home:
        text = text.replace(home, "%USERPROFILE%")
    appdata = os.environ.get("APPDATA")
    if appdata:
        text = text.replace(appdata, "%APPDATA%")
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        text = text.replace(localappdata, "%LOCALAPPDATA%")
    return text[:8000]


def redact(value: Any, *, key_hint: str = "") -> Any:
    if key_hint.casefold() in _SECRET_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(key)[:120]: redact(item, key_hint=str(key))
            for key, item in list(value.items())[:200]
        }
    if isinstance(value, list):
        return [redact(item) for item in value[:200]]
    if isinstance(value, tuple):
        return [redact(item) for item in value[:200]]
    if isinstance(value, str):
        return _safe_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_string(str(value))


def build_report_payload() -> dict[str, object]:
    base = diagnostics.run()
    disk = shutil.disk_usage(settings.runtime_dir)
    payload = {
        "product": {
            "name": "Jarvis Papa",
            "version": __version__,
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": Path(sys.executable).name,
        },
        "diagnostics": base,
        "memory": memory_store.status(),
        "storage": {
            "free_gb": round(disk.free / (1024**3), 2),
            "total_gb": round(disk.total / (1024**3), 2),
        },
    }
    return redact(payload)


def export_report(destination: Path | None = None) -> Path:
    if destination is None:
        desktop = Path.home() / "Desktop"
        base = desktop if desktop.is_dir() else settings.runtime_dir
        destination = base / "Rapport-Jarvis.zip"
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_report_payload()
    readme = (
        "Rapport de diagnostic Jarvis Papa\n"
        "================================\n\n"
        "Ce fichier contient uniquement des informations techniques utiles au diagnostic.\n"
        "Les secrets connus, chemins personnels et jetons sont masqués automatiquement.\n"
        "Aucun contenu de mail, document personnel ou cookie de navigateur n'est inclus.\n"
    )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostic.json",
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )
        archive.writestr("LISEZ-MOI.txt", readme)
    return destination
