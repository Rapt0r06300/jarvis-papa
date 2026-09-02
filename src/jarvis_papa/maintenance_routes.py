from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jarvis_papa.audit import audit_log
from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.restore_coordinator import restore_coordinator
from jarvis_papa.system_reliability import backup_manager, session_recovery, startup_manager
from jarvis_papa.update_manager import UpdateManifest, update_manager

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


class AuthorizedRequest(BaseModel):
    authorization_token: str = Field(default="", max_length=300)


class StartupPlanRequest(BaseModel):
    enabled: bool


class StartupConfigureRequest(AuthorizedRequest):
    enabled: bool


class RestorePlanRequest(BaseModel):
    backup_path: str = Field(min_length=1, max_length=4000)


class RestoreRequest(AuthorizedRequest):
    backup_path: str = Field(min_length=1, max_length=4000)


class UpdateCheckRequest(BaseModel):
    manifest_url: str = Field(min_length=8, max_length=3000)


class UpdateStageRequest(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    installer_url: str = Field(min_length=8, max_length=3000)
    sha256: str = Field(min_length=64, max_length=64)
    notes_url: str = Field(default="", max_length=3000)
    published_at: str = Field(default="", max_length=120)


def _consume(token: str, action_key: str, binding: dict[str, object]) -> bool:
    ok = confirmation_manager.consume(token, action_key, binding)
    audit_log.record(
        "authorization_consumed",
        action=action_key,
        ok=ok,
        metadata=binding,
    )
    return ok


@router.get("/status")
def maintenance_status() -> dict[str, object]:
    return {
        "ok": True,
        "startup": startup_manager.status(),
        "backups": backup_manager.recent(limit=10),
        "restore": restore_coordinator.status(),
        "recovery": session_recovery.status(),
        "updates": update_manager.status(),
    }


@router.post("/startup/plan")
def startup_plan(request: StartupPlanRequest) -> dict[str, object]:
    binding = {"enabled": request.enabled}
    return {
        "ok": True,
        "action_key": "system.startup.configure",
        "binding": binding,
        "description": (
            "Démarrer Jarvis automatiquement à chaque ouverture de cette session Windows."
            if request.enabled
            else "Ne plus démarrer Jarvis automatiquement avec cette session Windows."
        ),
    }


@router.post("/startup")
def configure_startup(request: StartupConfigureRequest) -> dict[str, object]:
    binding = {"enabled": request.enabled}
    if not _consume(request.authorization_token, "system.startup.configure", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Modification bloquée : deux autorisations exactes sont obligatoires.",
        }
    result = startup_manager.enable() if request.enabled else startup_manager.disable()
    audit_log.record(
        "startup_configured",
        action="system.startup.configure",
        ok=bool(result.get("ok")),
        metadata=binding,
    )
    return {"state": "success" if result.get("ok") else "failed", **result}


@router.post("/backups")
def create_backup() -> dict[str, object]:
    result = backup_manager.create("manual")
    audit_log.record("backup_created", action="backup.create", ok=result.ok)
    return {"state": "success" if result.ok else "failed", **result.to_dict()}


@router.get("/backups")
def list_backups() -> dict[str, object]:
    return {"ok": True, "items": backup_manager.recent(limit=30)}


@router.post("/restore/plan")
def restore_plan(request: RestorePlanRequest) -> dict[str, object]:
    path = Path(request.backup_path).expanduser().resolve()
    if not backup_manager.is_managed_backup(path):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Cette sauvegarde n'appartient pas au dépôt de sauvegardes géré par Jarvis.",
        }
    binding = {"backup_path": str(path)}
    return {
        "ok": True,
        "action_key": "backup.restore",
        "binding": binding,
        "description": (
            "Restaurer cette sauvegarde au prochain démarrage de Jarvis. Une sauvegarde de sécurité "
            "sera créée avant toute restauration."
        ),
    }


@router.post("/restore")
def stage_restore(request: RestoreRequest) -> dict[str, object]:
    path = Path(request.backup_path).expanduser().resolve()
    binding = {"backup_path": str(path)}
    if not backup_manager.is_managed_backup(path):
        return {"ok": False, "state": "failed", "detail": "Sauvegarde non gérée par Jarvis."}
    if not _consume(request.authorization_token, "backup.restore", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Restauration bloquée : deux autorisations exactes sont obligatoires.",
        }
    result = restore_coordinator.stage(path)
    audit_log.record(
        "restore_staged",
        action="backup.restore",
        ok=bool(result.get("ok")),
        metadata=binding,
    )
    return result


@router.post("/restore/cancel")
def cancel_restore() -> dict[str, object]:
    result = restore_coordinator.cancel()
    audit_log.record("restore_cancelled", action="backup.restore.cancel", ok=True)
    return result


@router.post("/updates/check")
def check_update(request: UpdateCheckRequest) -> dict[str, object]:
    return update_manager.check(request.manifest_url)


@router.post("/updates/stage")
def stage_update(request: UpdateStageRequest) -> dict[str, object]:
    manifest = UpdateManifest(
        version=request.version,
        installer_url=request.installer_url,
        sha256=request.sha256.casefold(),
        notes_url=request.notes_url,
        published_at=request.published_at,
    )
    result = update_manager.stage(manifest)
    audit_log.record(
        "update_staged",
        action="system.update.stage",
        ok=bool(result.get("ok")),
        metadata={"version": request.version},
    )
    return result


@router.get("/updates/install-plan")
def update_install_plan() -> dict[str, object]:
    status = update_manager.status()
    state = status.get("state") if isinstance(status.get("state"), dict) else {}
    version = str(state.get("version") or "")
    binding = {"version": version}
    if not status.get("pending") or not version:
        return {"ok": False, "state": "failed", "detail": "Aucune mise à jour vérifiée n'est prête."}
    return {
        "ok": True,
        "action_key": "system.update.install",
        "binding": binding,
        "description": f"Installer la mise à jour Jarvis {version} et redémarrer l'application.",
    }


@router.post("/updates/install")
def install_update(request: AuthorizedRequest) -> dict[str, object]:
    status = update_manager.status()
    state = status.get("state") if isinstance(status.get("state"), dict) else {}
    version = str(state.get("version") or "")
    binding = {"version": version}
    if not status.get("pending") or not version:
        return {"ok": False, "state": "failed", "detail": "Aucune mise à jour vérifiée n'est prête."}
    if not _consume(request.authorization_token, "system.update.install", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Installation bloquée : deux autorisations exactes sont obligatoires.",
        }
    result = update_manager.launch_staged()
    audit_log.record(
        "update_install_launched",
        action="system.update.install",
        ok=bool(result.get("ok")),
        metadata=binding,
    )
    return result


@router.get("/updates/rollback-plan")
def update_rollback_plan() -> dict[str, object]:
    status = update_manager.status()
    if not status.get("rollback_available"):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Aucune version précédente vérifiée n'est disponible.",
        }
    binding = {"rollback": "previous-installer"}
    return {
        "ok": True,
        "action_key": "system.update.rollback",
        "binding": binding,
        "description": "Réinstaller la dernière version précédente de Jarvis conservée localement.",
    }


@router.post("/updates/rollback")
def rollback_update(request: AuthorizedRequest) -> dict[str, object]:
    binding = {"rollback": "previous-installer"}
    if not _consume(request.authorization_token, "system.update.rollback", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Rollback bloqué : deux autorisations exactes sont obligatoires.",
        }
    result = update_manager.rollback()
    audit_log.record(
        "update_rollback_launched",
        action="system.update.rollback",
        ok=bool(result.get("ok")),
        metadata=binding,
    )
    return result
