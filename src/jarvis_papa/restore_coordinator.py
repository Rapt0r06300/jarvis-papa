from __future__ import annotations

import json
import os
import time
from pathlib import Path

from jarvis_papa.config import settings
from jarvis_papa.system_reliability import backup_manager


class RestoreCoordinator:
    """Stage a restore while Jarvis is running and apply it before services start."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.pending_path = data_dir / "pending-restore.json"

    def stage(self, backup_path: str | Path) -> dict[str, object]:
        if not backup_manager.is_managed_backup(backup_path):
            return {
                "ok": False,
                "state": "failed",
                "detail": "Seules les sauvegardes créées et conservées par Jarvis peuvent être restaurées.",
            }
        source = Path(backup_path).expanduser().resolve()
        safety = backup_manager.create("before-staged-restore")
        payload = {
            "backup_path": str(source),
            "staged_at": time.time(),
            "safety_backup": safety.path if safety.ok else "",
        }
        self._write(payload)
        return {
            "ok": True,
            "state": "partial",
            "restart_required": True,
            "backup_path": str(source),
            "safety_backup": safety.path if safety.ok else "",
            "detail": (
                "La restauration est prête. Elle sera appliquée au prochain démarrage, avant "
                "l'ouverture des bases de données Jarvis."
            ),
        }

    def apply_pending(self) -> dict[str, object]:
        payload = self._read()
        source = str(payload.get("backup_path") or "")
        if not source:
            return {"ok": True, "applied": False, "detail": "Aucune restauration en attente."}
        if not backup_manager.is_managed_backup(source):
            self.pending_path.unlink(missing_ok=True)
            return {
                "ok": False,
                "applied": False,
                "detail": "La sauvegarde en attente n'est plus valide ; restauration annulée.",
            }
        restored = backup_manager.restore(Path(source))
        if restored.ok:
            self.pending_path.unlink(missing_ok=True)
        return {
            **restored.to_dict(),
            "applied": restored.ok,
            "restart_required": False,
        }

    def status(self) -> dict[str, object]:
        payload = self._read()
        return {
            "ok": True,
            "pending": bool(payload.get("backup_path")),
            "pending_request": payload,
            "path": str(self.pending_path),
        }

    def cancel(self) -> dict[str, object]:
        existed = self.pending_path.is_file()
        self.pending_path.unlink(missing_ok=True)
        return {
            "ok": True,
            "state": "success",
            "detail": (
                "La restauration en attente a été annulée."
                if existed
                else "Aucune restauration n'était en attente."
            ),
        }

    def _read(self) -> dict[str, object]:
        try:
            payload = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict[str, object]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.pending_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.pending_path)


restore_coordinator = RestoreCoordinator(settings.data_dir)
