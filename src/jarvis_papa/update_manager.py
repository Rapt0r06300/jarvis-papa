from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from jarvis_papa import __version__
from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class UpdateManifest:
    version: str
    installer_url: str
    sha256: str
    notes_url: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class UpdateManager:
    """Fail-closed updater for a signed installer distributed from an HTTPS manifest."""

    MAX_INSTALLER_BYTES = 512 * 1024 * 1024

    def __init__(self, runtime_dir: Path, current_version: str = __version__) -> None:
        self.runtime_dir = runtime_dir
        self.current_version = current_version
        self.update_dir = runtime_dir / "updates"
        self.pending_installer = self.update_dir / "pending-installer.exe"
        self.current_installer = self.update_dir / "current-installer.exe"
        self.previous_installer = self.update_dir / "previous-installer.exe"
        self.state_path = self.update_dir / "update-state.json"

    def check(self, manifest_url: str) -> dict[str, object]:
        if not self._safe_https_url(manifest_url):
            return {
                "ok": False,
                "state": "failed",
                "detail": "Le canal de mise à jour doit utiliser HTTPS.",
            }
        try:
            response = httpx.get(manifest_url, timeout=10.0, follow_redirects=False)
            response.raise_for_status()
            payload = response.json()
            manifest = self._parse_manifest(payload)
            newer = self._version_tuple(manifest.version) > self._version_tuple(self.current_version)
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        return {
            "ok": True,
            "state": "success",
            "update_available": newer,
            "current_version": self.current_version,
            "manifest": manifest.to_dict(),
            "detail": (
                f"La version {manifest.version} est disponible."
                if newer
                else "Jarvis est déjà à jour."
            ),
        }

    def stage(self, manifest: UpdateManifest) -> dict[str, object]:
        try:
            if self._version_tuple(manifest.version) <= self._version_tuple(self.current_version):
                return {
                    "ok": False,
                    "state": "failed",
                    "detail": "Jarvis refuse d'installer automatiquement une version identique ou plus ancienne.",
                }
        except ValueError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        if not self._safe_https_url(manifest.installer_url):
            return {"ok": False, "state": "failed", "detail": "URL d'installeur non sûre."}
        if len(manifest.sha256) != 64 or any(
            char not in "0123456789abcdef" for char in manifest.sha256.casefold()
        ):
            return {"ok": False, "state": "failed", "detail": "Empreinte SHA-256 invalide."}
        self.update_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.pending_installer.with_suffix(".download")
        digest = hashlib.sha256()
        size = 0
        try:
            with httpx.stream(
                "GET",
                manifest.installer_url,
                timeout=30.0,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.MAX_INSTALLER_BYTES:
                            raise ValueError("L'installeur dépasse la taille maximale autorisée.")
                        digest.update(chunk)
                        handle.write(chunk)
        except (OSError, httpx.HTTPError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            return {"ok": False, "state": "failed", "detail": str(exc)}
        actual = digest.hexdigest()
        if actual.casefold() != manifest.sha256.casefold():
            temporary.unlink(missing_ok=True)
            return {
                "ok": False,
                "state": "failed",
                "detail": "Empreinte SHA-256 incorrecte ; mise à jour bloquée.",
            }
        signature = self._authenticode_status(temporary)
        if sys.platform == "win32" and signature != "Valid":
            temporary.unlink(missing_ok=True)
            return {
                "ok": False,
                "state": "failed",
                "detail": f"Signature Authenticode non valide ({signature}) ; mise à jour bloquée.",
            }
        os.replace(temporary, self.pending_installer)
        self._write_state(
            {
                "status": "staged",
                "version": manifest.version,
                "sha256": actual,
                "staged_at": time.time(),
                "signature": signature,
            }
        )
        return {
            "ok": True,
            "state": "success",
            "installer": str(self.pending_installer),
            "version": manifest.version,
            "signature": signature,
            "detail": "Mise à jour téléchargée, vérifiée et prête à installer.",
        }

    def launch_staged(self) -> dict[str, object]:
        if not self.pending_installer.is_file():
            return {"ok": False, "state": "failed", "detail": "Aucune mise à jour prête."}
        if sys.platform != "win32":
            return {"ok": False, "state": "failed", "detail": "Installation disponible sur Windows."}
        signature = self._authenticode_status(self.pending_installer)
        if signature != "Valid":
            return {
                "ok": False,
                "state": "failed",
                "detail": f"Signature Authenticode non valide ({signature}).",
            }
        self.update_dir.mkdir(parents=True, exist_ok=True)
        if self.current_installer.is_file():
            shutil.copy2(self.current_installer, self.previous_installer)
        self._write_state(
            {
                **self._read_state(),
                "status": "installing",
                "launched_at": time.time(),
                "previous_installer": str(self.previous_installer),
            }
        )
        try:
            subprocess.Popen(
                [str(self.pending_installer), "/SILENT", "/NORESTART"],
                close_fds=True,
            )
        except OSError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        return {
            "ok": True,
            "state": "partial",
            "detail": "L'installeur vérifié a été lancé. Jarvis va devoir redémarrer.",
        }

    def rollback(self) -> dict[str, object]:
        if sys.platform != "win32":
            return {"ok": False, "state": "failed", "detail": "Rollback disponible sur Windows."}
        if not self.previous_installer.is_file():
            return {
                "ok": False,
                "state": "failed",
                "detail": "Aucun installeur précédent vérifié n'est disponible.",
            }
        signature = self._authenticode_status(self.previous_installer)
        if signature != "Valid":
            return {
                "ok": False,
                "state": "failed",
                "detail": f"Ancien installeur non signé ou invalide ({signature}).",
            }
        try:
            subprocess.Popen(
                [str(self.previous_installer), "/SILENT", "/NORESTART"],
                close_fds=True,
            )
        except OSError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        self._write_state({**self._read_state(), "status": "rollback-launched"})
        return {
            "ok": True,
            "state": "partial",
            "detail": "La réinstallation de la version précédente a été lancée.",
        }

    def status(self) -> dict[str, object]:
        return {
            "ok": True,
            "current_version": self.current_version,
            "pending": self.pending_installer.is_file(),
            "rollback_available": self.previous_installer.is_file(),
            "state": self._read_state(),
        }

    @staticmethod
    def _parse_manifest(payload: object) -> UpdateManifest:
        if not isinstance(payload, dict):
            raise ValueError("Manifest de mise à jour invalide.")
        version = str(payload.get("version") or "").strip()
        installer_url = str(payload.get("installer_url") or "").strip()
        sha256 = str(payload.get("sha256") or "").strip().casefold()
        if not version or not installer_url or not sha256:
            raise ValueError("Manifest de mise à jour incomplet.")
        return UpdateManifest(
            version=version,
            installer_url=installer_url,
            sha256=sha256,
            notes_url=str(payload.get("notes_url") or "").strip(),
            published_at=str(payload.get("published_at") or "").strip(),
        )

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        core = value.strip().lstrip("vV").split("-", 1)[0]
        parts = core.split(".")
        if not parts or any(not part.isdigit() for part in parts):
            raise ValueError(f"Version invalide : {value}")
        return tuple(int(part) for part in parts)

    @staticmethod
    def _safe_https_url(value: str) -> bool:
        parsed = urlparse(value.strip())
        return parsed.scheme.casefold() == "https" and bool(parsed.netloc)

    @staticmethod
    def _authenticode_status(path: Path) -> str:
        if sys.platform != "win32":
            return "NotApplicable"
        script = (
            "& { param([string]$p) "
            "(Get-AuthenticodeSignature -LiteralPath $p).Status.ToString() }"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "UnknownError"
        if completed.returncode != 0:
            return "UnknownError"
        return completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "Unknown"

    def _read_state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, payload: dict[str, object]) -> None:
        self.update_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)


update_manager = UpdateManager(settings.runtime_dir)
