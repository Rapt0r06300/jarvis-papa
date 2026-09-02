from __future__ import annotations

import json
import os
import shutil
import stat
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
    EXCLUDED_RUNTIME_NAMES = {
        "audit.1.jsonl",
        "audit.jsonl",
        "circuit-breakers.json",
        "desktop-session-active.json",
        "kill-switch.json",
    }
    MAX_FILE_BYTES = 64 * 1024 * 1024
    MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
    MAX_ARCHIVE_FILES = 5000

    def __init__(self, data_dir: Path, runtime_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.runtime_dir = runtime_dir.resolve()
        self.backup_dir = self.data_dir / "backups"

    def create(self, label: str = "manual") -> BackupResult:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        clean_label = "".join(char for char in label.casefold() if char.isalnum() or char == "-")
        destination = self.backup_dir / f"jarvis-{clean_label or 'backup'}-{timestamp}.zip"
        suffix = 1
        while destination.exists():
            destination = self.backup_dir / (
                f"jarvis-{clean_label or 'backup'}-{timestamp}-{suffix}.zip"
            )
            suffix += 1
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
        except (OSError, zipfile.BadZipFile) as exc:
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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        safety = self.create("pre-restore")
        if not safety.ok and self._files_to_backup():
            return BackupResult(
                False,
                str(source),
                0,
                "Restauration bloquée : la sauvegarde de sécurité préalable a échoué.",
            )
        try:
            with zipfile.ZipFile(source) as archive:
                members = self._validated_members(archive)
                if not members:
                    return BackupResult(False, str(source), 0, "Archive vide ou invalide.")
                with tempfile.TemporaryDirectory(dir=self.data_dir) as temp_dir:
                    extracted = Path(temp_dir)
                    for info in members:
                        archive.extract(info, extracted)
                        relative = PurePosixPath(info.filename)
                        candidate = extracted.joinpath(*relative.parts)
                        target = self.data_dir.joinpath(*relative.parts)
                        if not self._safe_target(target):
                            return BackupResult(
                                False,
                                str(source),
                                0,
                                "La cible de restauration sort du dossier Jarvis.",
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary_target = target.with_suffix(target.suffix + ".restore-tmp")
                        shutil.copy2(candidate, temporary_target)
                        os.replace(temporary_target, target)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
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

    def is_managed_backup(self, raw_path: str | Path) -> bool:
        try:
            path = Path(raw_path).expanduser().resolve()
            path.relative_to(self.backup_dir.resolve())
        except (OSError, ValueError):
            return False
        return path.is_file() and path.suffix.casefold() == ".zip"

    def _files_to_backup(self) -> list[tuple[Path, str]]:
        files: list[tuple[Path, str]] = []
        secret_store = self.data_dir / "protected-secrets.json"
        if self._eligible(secret_store):
            files.append((secret_store, "protected-secrets.json"))
        if self.runtime_dir.is_dir():
            for path in self.runtime_dir.rglob("*"):
                if not self._eligible_runtime(path):
                    continue
                try:
                    relative = path.relative_to(self.data_dir)
                except ValueError:
                    continue
                files.append((path, relative.as_posix()))
        return sorted(files, key=lambda item: item[1])

    def _eligible_runtime(self, path: Path) -> bool:
        if not self._eligible(path):
            return False
        try:
            relative = path.relative_to(self.runtime_dir)
        except ValueError:
            return False
        if not relative.parts:
            return False
        if relative.parts[0].casefold() == "updates":
            return False
        return relative.as_posix().casefold() not in self.EXCLUDED_RUNTIME_NAMES

    def _eligible(self, path: Path) -> bool:
        if not path.is_file() or path.suffix.casefold() in self.EXCLUDED_SUFFIXES:
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        return 0 <= size <= self.MAX_FILE_BYTES

    def _validated_members(self, archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        members: list[zipfile.ZipInfo] = []
        seen: set[str] = set()
        total = 0
        for info in archive.infolist():
            if info.filename == "backup-manifest.json":
                continue
            if info.is_dir() or not self._safe_member(info.filename):
                raise ValueError("Archive de sauvegarde contenant un chemin non autorisé.")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError("Les liens symboliques sont interdits dans une sauvegarde Jarvis.")
            if info.file_size < 0 or info.file_size > self.MAX_FILE_BYTES:
                raise ValueError("Un fichier de sauvegarde dépasse la taille maximale autorisée.")
            normalized = PurePosixPath(info.filename).as_posix().casefold()
            if normalized in seen:
                raise ValueError("Archive de sauvegarde contenant des chemins en doublon.")
            seen.add(normalized)
            total += info.file_size
            if total > self.MAX_ARCHIVE_BYTES:
                raise ValueError("La sauvegarde dépasse la taille totale maximale autorisée.")
            members.append(info)
            if len(members) > self.MAX_ARCHIVE_FILES:
                raise ValueError("La sauvegarde contient trop de fichiers.")
        return members

    def _safe_target(self, target: Path) -> bool:
        try:
            target.resolve(strict=False).relative_to(self.data_dir)
        except (OSError, ValueError):
            return False
        return True

    @staticmethod
    def _safe_member(name: str) -> bool:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            return False
        if path.parts == ("protected-secrets.json",):
            return True
        return len(path.parts) >= 2 and path.parts[0] == "runtime"


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
