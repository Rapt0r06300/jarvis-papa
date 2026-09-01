from __future__ import annotations

from fastapi import APIRouter, HTTPException

from jarvis_papa.thunderbird import thunderbird_bridge_state, thunderbird_commands

router = APIRouter(prefix="/api/advanced/thunderbird", tags=["advanced-thunderbird"])


@router.post("/account-probe")
def start_account_probe() -> dict[str, object]:
    bridge = thunderbird_bridge_state.snapshot()
    if not bool(bridge.get("connected")):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Le pont Thunderbird n'est pas connecté. Ouvre Thunderbird puis réessaie.",
        }
    command = thunderbird_commands.enqueue(
        "inspect_accounts",
        {},
        context={"purpose": "final_pc_validation"},
    )
    return {
        "ok": True,
        "state": "partial",
        "command_id": command.id,
        "detail": "Je vérifie seulement qu'un compte mail réel est configuré dans Thunderbird.",
    }


@router.get("/account-probe/{command_id}")
def account_probe_result(command_id: str) -> dict[str, object]:
    command = thunderbird_commands.get(command_id)
    if command is None or command.kind != "inspect_accounts":
        raise HTTPException(status_code=404, detail="Sonde Thunderbird introuvable.")
    if command.status == "pending":
        return {
            "ok": True,
            "state": "partial",
            "command_id": command.id,
            "detail": "Thunderbird vérifie les comptes configurés.",
        }
    if command.status == "failed":
        return {
            "ok": False,
            "state": "failed",
            "command_id": command.id,
            "detail": command.error or "Thunderbird n'a pas pu vérifier les comptes.",
        }
    result = command.result
    verified = result.get("verified") is True
    mail_accounts = int(result.get("mail_account_count") or 0)
    folders = int(result.get("folder_accessible_count") or 0)
    ready = verified and mail_accounts >= 1 and folders >= 1
    return {
        "ok": ready,
        "state": "success" if ready else "failed",
        "command_id": command.id,
        "verified": verified,
        "account_count": int(result.get("account_count") or 0),
        "mail_account_count": mail_accounts,
        "folder_accessible_count": folders,
        "detail": (
            "Thunderbird a confirmé qu'au moins un compte mail et ses dossiers sont accessibles."
            if ready
            else "Aucun compte mail IMAP/POP exploitable n'a été confirmé par Thunderbird."
        ),
    }
