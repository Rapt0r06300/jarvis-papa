from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class BackupResult:
    ok: bool
    path: str
    files: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class WindowsStartupManager:
    """Per-user logon registration; it never asks for administrator rights."""

    KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE = "Jarvis Papa"

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def command(self) -> str:
        if bool(getattr(sys, "frozen", False)):
            arguments = [sys.executable]
        else:
            arguments = [sys.executable, "-m", "jarvis_papa.professional_desktop_plus"]
        return subprocess.list2cmdline(arguments)

    def status(self) -> dict[str, object]:
        if not self.available:
            return {"ok": False, "enabled": False, "detail": "Disponible uniquement sur Windows."}
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
                value, _ = winreg.QueryValueEx(key, self.VALUE)
        except FileNotFoundError:
            value = ""
        except OSError as exc:
            return {"ok": False, "enabled": False, "detail": str(exc)}
        expected = self.command()
        return {
            "ok": True,
            "enabled": str(value) == expected,
            "command": str(value),
            "expected_command": expected,
        }

    def enable(self) -> dict[str, object]:
        if not self.available:
            return {"ok": False, "enabled": False, "detail": "Disponible uniquement sur Windows."}
        import winreg

        command = self.command()
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
                winreg.SetValueEx(key, self.VALUE, 0, winreg.REG_SZ, command)
        except OSError as exc:
            return {"ok": False, "enabled": False, "detail": str(exc)}
        result = self.status()
        result["detail"] = (
            "Jarvis démarrera avec cette session Windows."
            if result.get("enabled")
            else "Windows n'a pas confirmé le démarrage automatique."
        )
        return result

    def disable(self) -> dict[str, object]:
        if not self.available:
            return {"ok": False, "enabled": False, "detail": "Disponible uniquement sur Windows."}
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                try:
                    winreg.DeleteValue(key, self.VALUE)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        except OSError as exc:
            return {"ok": False, "enabled": True, "detail": str(exc)}
        result = self.status()
        result["detail"] = "Jarvis ne démarrera plus automatiquement avec Windows."
        return result


class BackupManager:
    """Bounded local backups for durable Jarvis state and DPAPI ciphertext."""

    EXCLUDED_SUFFIXES = {".lock", ".log", ".tmp", ".wav", ".mp3"}
    MAX_FILE_BYTES = 64 * 1024 * 1024

    def __init__(self, data_dir: Path, runtime_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.runtime_dir = runtime_dir.resolve()
        self.backup_dir = self.data_dir / "backups"

    def create(self, label: str = "manual") -> BackupResult:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        clean_label = "".join(char for char in label.casefold() if char.isalnum() or char == "-")
        destination = self.backup_dir / f"jarvis-{clean_label or 'backup'}-{timestamp}.zip"
        files = self._files_to_backup()
        if not files:
            return BackupResult(False, "", 0, "Aucune donnée durable n'a été trouvée.")
        temporary = destination.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, arcname in files:
                    archive.write(path, arcname)
                manifest = {
                    "version": 1,
                    "created_at": time.time(),
                    "files": [arcname for _, arcname in files],
                }
                archive.writestr("backup-manifest.json", json.dumps(manifest, indent=2))
            os.replace(temporary, destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            return BackupResult(False, "", 0, str(exc))
        return BackupResult(
            True,
            str(destination),
            len(files),
            f"Sauvegarde créée avec {len(files)} fichier(s) durable(s).",
        )

    def restore(self, backup_path: Path) -> BackupResult:
        source = backup_path.expanduser().resolve()
        if not source.is_file() or source.suffix.casefold() != ".zip":
            return BackupResult(False, str(source), 0, "Sauvegarde ZIP introuvable.")
        try:
            with zipfile.ZipFile(source) as archive:
                members = [name for name in archive.namelist() if name != "backup-manifest.json"]
                if not members or any(not self._safe_member(name) for name in members):
                    return BackupResult(False, str(source), 0, "Archive invalide ou chemin non sûr.")
                with tempfile.TemporaryDirectory(dir=self.data_dir) as temp_dir:
                    extracted = Path(temp_dir)
                    archive.extractall(extracted)
                    for member in members:
                        candidate = extracted / PurePosixPath(member)
                        target = self.data_dir / PurePosixPath(member)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(candidate, target)
        except (OSError, zipfile.BadZipFile) as exc:
            return BackupResult(False, str(source), 0, str(exc))
        return BackupResult(
            True,
            str(source),
            len(members),
            f"{len(members)} fichier(s) ont été restaurés.",
        )

    def recent(self, limit: int = 10) -> list[str]:
        if not self.backup_dir.is_dir():
            return []
        backups = sorted(
            self.backup_dir.glob("jarvis-*.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [str(path) for path in backups[: max(1, min(int(limit), 30))]]

    def _files_to_backup(self) -> list[tuple[Path, str]]:
        files: list[tuple[Path, str]] = []
        secret_store = self.data_dir / "protected-secrets.json"
        if self._eligible(secret_store):
            files.append((secret_store, "protected-secrets.json"))
        if self.runtime_dir.is_dir():
            for path in self.runtime_dir.rglob("*"):
                if not self._eligible(path):
                    continue
                relative = path.relative_to(self.data_dir)
                files.append((path, relative.as_posix()))
        return sorted(files, key=lambda item: item[1])

    def _eligible(self, path: Path) -> bool:
        if not path.is_file() or path.suffix.casefold() in self.EXCLUDED_SUFFIXES:
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        return 0 <= size <= self.MAX_FILE_BYTES

    @staticmethod
    def _safe_member(name: str) -> bool:
        path = PurePosixPath(name)
        return bool(name) and not path.is_absolute() and ".." not in path.parts


class SessionRecovery:
    """Detect a previous unclean desktop shutdown after the single-instance lock is held."""

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.marker = runtime_dir / "desktop-session-active.json"
        self.report = runtime_dir / "last-unclean-shutdown.json"

    def begin(self) -> dict[str, object]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        previous: dict[str, object] = {}
        if self.marker.is_file():
            try:
                loaded = json.loads(self.marker.read_text(encoding="utf-8"))
                previous = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                previous = {}
            report = {
                "detected_at": time.time(),
                "previous_session": previous,
                "detail": "Le lancement précédent ne s'est pas terminé proprement.",
            }
            self._atomic_json(self.report, report)
        current = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "executable": sys.executable,
        }
        self._atomic_json(self.marker, current)
        return {
            "ok": True,
            "previous_unclean": bool(previous),
            "previous_session": previous,
        }

    def end(self) -> None:
        self.marker.unlink(missing_ok=True)

    def status(self) -> dict[str, object]:
        return {
            "ok": True,
            "active_marker": self.marker.is_file(),
            "unclean_report": self.report.is_file(),
            "report_path": str(self.report),
        }

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)


startup_manager = WindowsStartupManager()
backup_manager = BackupManager(settings.data_dir, settings.runtime_dir)
session_recovery = SessionRecovery(settings.runtime_dir)
