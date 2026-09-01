from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis_papa.actions import ActionKind, ActionOption, action_queue
from jarvis_papa.audit import audit_log
from jarvis_papa.browser_workflow import browser_workflow
from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.memory_semantic import semantic_memory_store
from jarvis_papa.repair import repair_service
from jarvis_papa.thunderbird import ThunderbirdCommand, thunderbird_commands
from jarvis_papa.voice import voice_service
from jarvis_papa.windows_skills import windows_skills

router = APIRouter(prefix="/api/advanced", tags=["advanced"])


class AuthorizedRequest(BaseModel):
    authorization_token: str = Field(default="", max_length=300)


class DraftInspectRequest(BaseModel):
    draft_command_id: str = Field(min_length=8, max_length=100)


class SendPreparedRequest(AuthorizedRequest):
    inspect_command_id: str = Field(min_length=8, max_length=100)


class ThunderbirdAckRequest(BaseModel):
    ok: bool
    error: str | None = Field(default=None, max_length=1200)
    result: dict[str, object] = Field(default_factory=dict)


class BrowserInspectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=3000)


class BrowserExecuteRequest(AuthorizedRequest):
    url: str = Field(min_length=8, max_length=3000)
    fields: dict[str, str] = Field(default_factory=dict)
    button_text: str = Field(min_length=1, max_length=300)
    verify_text: str = Field(default="", max_length=500)
    session_name: str = Field(default="default", max_length=60)


class WindowsPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4000)


class WindowsDialogRequest(AuthorizedRequest):
    window_title: str = Field(min_length=1, max_length=300)
    path: str = Field(min_length=1, max_length=4000)


class WindowsPrintRequest(AuthorizedRequest):
    path: str = Field(min_length=1, max_length=4000)


class WindowsSettingsRequest(BaseModel):
    page: str = Field(default="printers", max_length=80)


class RepairRequest(AuthorizedRequest):
    components: list[str] = Field(min_length=1, max_length=8)


def _consume(token: str, action_key: str, binding: dict[str, object]) -> bool:
    ok = confirmation_manager.consume(token, action_key, binding)
    audit_log.record("authorization_consumed", action=action_key, ok=ok)
    return ok


def _command_or_404(command_id: str) -> ThunderbirdCommand:
    command = thunderbird_commands.get(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Commande Thunderbird introuvable.")
    return command


def _send_binding(card_id: str, inspect: ThunderbirdCommand) -> dict[str, object]:
    result = inspect.result
    return {
        "card_id": card_id,
        "inspect_command_id": inspect.id,
        "compose_tab_id": int(result.get("compose_tab_id") or 0),
        "compose_digest": str(result.get("compose_digest") or ""),
        "recipient_display": str(result.get("recipient_display") or ""),
        "subject": str(result.get("subject") or ""),
        "attachment_names": list(result.get("attachment_names") or []),
    }


def _send_description(binding: dict[str, object]) -> str:
    recipient = str(binding.get("recipient_display") or "le destinataire du brouillon")
    subject = str(binding.get("subject") or "sans objet")
    attachments = binding.get("attachment_names")
    names = [str(item) for item in attachments] if isinstance(attachments, list) else []
    attachment_text = (
        " avec la pièce jointe " + ", ".join(names[:4]) if names else " sans pièce jointe"
    )
    return f"Jarvis va envoyer le mail à {recipient}, objet « {subject} »{attachment_text}."


@router.post("/mail/{card_id}/send/inspect")
def inspect_prepared_mail(card_id: str, request: DraftInspectRequest) -> dict[str, object]:
    card = action_queue.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Tâche mail introuvable.")
    draft = _command_or_404(request.draft_command_id)
    if draft.kind != "prepare_reply" or draft.status != "succeeded":
        return {
            "ok": False,
            "state": "failed",
            "detail": "Le brouillon n'est pas encore confirmé comme prêt par Thunderbird.",
        }
    compose_tab_id = int(draft.result.get("compose_tab_id") or 0)
    if compose_tab_id <= 0:
        return {
            "ok": False,
            "state": "failed",
            "detail": (
                "Thunderbird n'a pas fourni l'identifiant du brouillon. "
                "Prépare à nouveau le brouillon."
            ),
        }
    command = thunderbird_commands.enqueue(
        "inspect_compose",
        {"compose_tab_id": compose_tab_id},
        context={"card_id": card_id, "draft_command_id": draft.id},
    )
    return {
        "ok": True,
        "state": "partial",
        "command_id": command.id,
        "detail": (
            "Je vérifie le destinataire, l'objet, les pièces jointes et le contenu exact du "
            "brouillon avant de demander ton accord."
        ),
    }


@router.get("/mail/{card_id}/send/plan/{inspect_command_id}")
def send_plan(card_id: str, inspect_command_id: str) -> dict[str, object]:
    card = action_queue.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Tâche mail introuvable.")
    inspect = _command_or_404(inspect_command_id)
    if inspect.kind != "inspect_compose" or inspect.status != "succeeded":
        return {
            "ok": False,
            "state": "partial" if inspect.status == "pending" else "failed",
            "detail": inspect.error or "La vérification du brouillon n'est pas terminée.",
        }
    binding = _send_binding(card_id, inspect)
    if not binding["compose_digest"] or not binding["compose_tab_id"]:
        return {
            "ok": False,
            "state": "failed",
            "detail": "La preuve du contenu du brouillon est incomplète. Jarvis refuse l'envoi.",
        }
    return {
        "ok": True,
        "state": "success",
        "action_key": "mail.send_reply",
        "binding": binding,
        "description": _send_description(binding),
        "recipient": binding["recipient_display"],
        "subject": binding["subject"],
        "attachment_names": binding["attachment_names"],
    }


@router.post("/mail/{card_id}/send")
def send_prepared_mail(card_id: str, request: SendPreparedRequest) -> dict[str, object]:
    card = action_queue.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Tâche mail introuvable.")
    inspect = _command_or_404(request.inspect_command_id)
    if inspect.kind != "inspect_compose" or inspect.status != "succeeded":
        return {"ok": False, "state": "failed", "detail": "Le brouillon n'a pas été vérifié."}
    binding = _send_binding(card_id, inspect)
    if not binding["compose_digest"] or not binding["compose_tab_id"]:
        return {"ok": False, "state": "failed", "detail": "Preuve de brouillon incomplète."}
    if not _consume(request.authorization_token, "mail.send_reply", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": (
                "Envoi bloqué : deux autorisations exactes et encore valides sont obligatoires."
            ),
        }
    command = thunderbird_commands.enqueue(
        "send_reply",
        {
            "compose_tab_id": binding["compose_tab_id"],
            "expected_compose_digest": binding["compose_digest"],
        },
        context={
            "card_id": card_id,
            "recipient_display": binding["recipient_display"],
            "subject": binding["subject"],
            "attachment_names": binding["attachment_names"],
        },
    )
    audit_log.record(
        "command_queued",
        action="mail.send_reply",
        ok=True,
        metadata={"command_id": command.id, "card_id": card_id},
    )
    return {
        "ok": True,
        "state": "partial",
        "command_id": command.id,
        "detail": (
            "J'ai demandé l'envoi à Thunderbird. Je n'annoncerai la réussite qu'après sa "
            "confirmation vérifiée."
        ),
    }


@router.post("/thunderbird/commands/{command_id}/ack")
def advanced_thunderbird_ack(
    command_id: str,
    request: ThunderbirdAckRequest,
) -> dict[str, object]:
    command = _command_or_404(command_id)
    incoming_result = request.result if isinstance(request.result, dict) else {}
    if command.status == "succeeded" and bool(incoming_result.get("duplicate")):
        return {"ok": True, "duplicate": True, "command": command.to_dict()}

    ok = request.ok
    error = request.error
    if command.kind == "send_reply" and ok:
        verified = (
            incoming_result.get("verified") is True
            and str(incoming_result.get("mode") or "") == "sendNow"
            and bool(str(incoming_result.get("header_message_id") or ""))
        )
        if not verified:
            ok = False
            error = (
                "Thunderbird n'a pas fourni une preuve suffisante d'envoi immédiat. "
                "Jarvis refuse de considérer le mail comme envoyé."
            )
    if command.kind == "inspect_compose" and ok:
        verified = incoming_result.get("verified") is True and bool(
            str(incoming_result.get("compose_digest") or "")
        )
        if not verified:
            ok = False
            error = "L'instantané du brouillon n'a pas pu être vérifié."

    acknowledged = thunderbird_commands.acknowledge(
        command_id,
        ok=ok,
        error=error,
        result=incoming_result,
    )
    if not acknowledged:
        raise HTTPException(status_code=404, detail="Commande Thunderbird introuvable.")
    command = _command_or_404(command_id)

    card_id = str(command.context.get("card_id") or "")
    if ok and command.kind == "sort_newsletters":
        card_ids = command.context.get("card_ids")
        if isinstance(card_ids, list):
            action_queue.remove_many([str(item) for item in card_ids])
    elif ok and command.kind == "prepare_reply" and card_id:
        compose_tab_id = int(command.result.get("compose_tab_id") or 0)
        card = action_queue.get(card_id)
        if card is not None and compose_tab_id > 0:
            card.metadata["draft_command_id"] = command.id
            card.metadata["compose_tab_id"] = compose_tab_id
            card.options = [item for item in card.options if item.id != "send-prepared"]
            card.options.append(
                ActionOption(
                    id="send-prepared",
                    label="Envoyer ce brouillon",
                    kind=ActionKind.SEND_REPLY,
                    payload={"draft_command_id": command.id},
                    requires_confirmation=False,
                )
            )
            action_queue.add(card)
    elif ok and command.kind == "send_reply" and card_id:
        recipient = str(command.context.get("recipient_display") or "destinataire")
        semantic_memory_store.record_action(
            "send_email",
            recipient,
            {"verified": True, "command_id": command.id},
        )
        action_queue.remove(card_id)

    audit_log.record(
        "command_ack",
        action=command.kind,
        ok=ok,
        detail=error or "",
        metadata={"command_id": command_id, "verified": command.result.get("verified")},
    )
    return {"ok": True, "command": command.to_dict()}


@router.post("/browser/inspect")
def browser_inspect(request: BrowserInspectRequest) -> dict[str, object]:
    return browser_workflow.inspect(request.url)


@router.post("/browser/execute")
def browser_execute(request: BrowserExecuteRequest) -> dict[str, object]:
    binding = {
        "url": request.url,
        "fields": request.fields,
        "button_text": request.button_text,
        "verify_text": request.verify_text,
        "session_name": request.session_name,
    }
    if not _consume(request.authorization_token, "browser.execute_workflow", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Interaction Web bloquée : double autorisation requise.",
        }
    return browser_workflow.execute(
        raw_url=request.url,
        fields=request.fields,
        button_text=request.button_text,
        verify_text=request.verify_text,
        session_name=request.session_name,
    )


@router.post("/windows/reveal")
def windows_reveal(request: WindowsPathRequest) -> dict[str, object]:
    return windows_skills.reveal_path(request.path).to_dict()


@router.post("/windows/file-dialog")
def windows_file_dialog(request: WindowsDialogRequest) -> dict[str, object]:
    try:
        canonical = str(Path(request.path).expanduser().resolve())
    except OSError:
        canonical = request.path
    binding = {"window_title": request.window_title, "path": canonical}
    if not _consume(request.authorization_token, "windows.choose_file", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Sélection bloquée : double autorisation requise.",
        }
    return windows_skills.choose_file_in_dialog(request.window_title, canonical).to_dict()


@router.post("/windows/print")
def windows_print(request: WindowsPrintRequest) -> dict[str, object]:
    try:
        canonical = str(Path(request.path).expanduser().resolve())
    except OSError:
        canonical = request.path
    binding = {"path": canonical, "operation": "print"}
    if not _consume(request.authorization_token, "windows.print_document", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Impression bloquée : double autorisation requise.",
        }
    return windows_skills.print_document(canonical).to_dict()


@router.post("/windows/settings")
def windows_settings(request: WindowsSettingsRequest) -> dict[str, object]:
    return windows_skills.open_windows_settings(request.page).to_dict()


@router.get("/repair/plan")
def repair_plan() -> dict[str, object]:
    return repair_service.plan()


@router.post("/repair")
def repair_execute(request: RepairRequest) -> dict[str, object]:
    components = sorted({item.strip().casefold() for item in request.components if item.strip()})
    binding = {"components": components}
    if not _consume(request.authorization_token, "jarvis.repair", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Réparation bloquée : double autorisation requise.",
        }
    result = repair_service.repair(components)
    audit_log.record(
        "self_repair",
        action="jarvis.repair",
        ok=bool(result.get("ok")),
        metadata={"components": components, "state": result.get("state")},
    )
    return result


@router.post("/voice/stop")
def voice_stop() -> dict[str, object]:
    stopped = voice_service.stop(clear_queue=True)
    return {
        "ok": True,
        "state": "success",
        "stopped": stopped,
        "detail": "J'ai arrêté la parole en cours." if stopped else "Aucune parole n'était en cours.",
    }


@router.get("/voice/quality")
def voice_quality() -> dict[str, object]:
    status = voice_service.status()
    providers = status.get("providers") if isinstance(status.get("providers"), dict) else {}
    order = status.get("provider_order") if isinstance(status.get("provider_order"), list) else []
    available = [
        name
        for name in order
        if isinstance(providers.get(name), dict) and providers[name].get("available")
    ]
    best = available[0] if available else None
    return {
        "ok": bool(best),
        "state": "success" if best else "failed",
        "best_provider": best,
        "premium_ready": best in {"elevenlabs", "azure", "qwen3"},
        "local_ready": any(name in available for name in ("qwen3", "windows")),
        "detail": (
            "Une voix naturelle de haute qualité est prête."
            if best in {"elevenlabs", "azure", "qwen3"}
            else "Jarvis peut parler, mais la voix premium n'est pas encore configurée."
            if best
            else "Aucun moteur vocal n'est prêt."
        ),
    }
