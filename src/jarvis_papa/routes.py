from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from jarvis_papa import __version__
from jarvis_papa.actions import ActionKind, action_queue
from jarvis_papa.agent import jarvis_agent
from jarvis_papa.ai import local_ai
from jarvis_papa.attachments import attachment_broker
from jarvis_papa.audit import audit_log
from jarvis_papa.browser import browser_agent
from jarvis_papa.config import settings
from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.dashboard import dashboard_html
from jarvis_papa.desktop import desktop_controller
from jarvis_papa.files import file_searcher
from jarvis_papa.http_security import install_http_security
from jarvis_papa.mail import IncomingMail, mail_assistant
from jarvis_papa.memory import memory_store
from jarvis_papa.security import ActionDecision, ActionRisk, security_policy
from jarvis_papa.speech import SpeechEvent, SpeechImportance, speech_coordinator
from jarvis_papa.thunderbird import thunderbird_commands
from jarvis_papa.windows_automation import windows_uia


class SensitiveRequest(BaseModel):
    authorization_token: str = Field(default="", max_length=200)
    confirmations: int = Field(default=0, ge=0, le=2)
    confirmed: bool = False


class SecurityCheckRequest(SensitiveRequest):
    risk: ActionRisk


class ConfirmationStartRequest(BaseModel):
    action_key: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=500)
    binding: dict[str, object] = Field(default_factory=dict)


class SpeechEventRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    importance: SpeechImportance = SpeechImportance.NORMAL
    user_initiated: bool = False
    action_required: bool = False
    dedupe_key: str | None = Field(default=None, max_length=300)
    sensitive: bool = False


class IncomingMailRequest(BaseModel):
    message_id: int | None = None
    header_message_id: str | None = Field(default=None, max_length=1000)
    author: str = Field(default="", max_length=1000)
    subject: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=50000)
    folder: str = Field(default="Inbox", max_length=500)
    list_unsubscribe: bool = False
    junk: bool = False
    date: str | None = Field(default=None, max_length=100)


class ActionExecuteRequest(SensitiveRequest):
    option_id: str = Field(min_length=1, max_length=100)


class AttachmentReplyRequest(SensitiveRequest):
    paths: list[str] = Field(min_length=1, max_length=5)


class SnoozeRequest(SensitiveRequest):
    hours: float = Field(default=4.0, ge=0.25, le=168.0)


class OpenPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4000)


class StartAppRequest(BaseModel):
    app: str = Field(min_length=1, max_length=80)


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class BrowserReadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=3000)


class BrowserDownloadRequest(SensitiveRequest):
    url: str = Field(min_length=8, max_length=3000)
    link_text: str = Field(min_length=1, max_length=500)


class AssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    speak: bool = True


class RememberRequest(SensitiveRequest):
    category: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=3000)


class UIAInspectRequest(BaseModel):
    window_title: str = Field(min_length=1, max_length=300)


class UIAInvokeRequest(SensitiveRequest):
    window_title: str = Field(min_length=1, max_length=300)
    control_name: str = Field(min_length=1, max_length=300)
    control_type: str | None = Field(default=None, max_length=80)


class UIASetTextRequest(SensitiveRequest):
    window_title: str = Field(min_length=1, max_length=300)
    control_name: str = Field(min_length=1, max_length=300)
    text: str = Field(max_length=10000)


class ThunderbirdAckRequest(BaseModel):
    ok: bool
    error: str | None = Field(default=None, max_length=1200)


def decision_payload(decision: ActionDecision) -> dict[str, object]:
    return {
        "allowed": decision.allowed,
        "requires_confirmation": decision.requires_confirmation,
        "confirmations_required": decision.confirmations_required,
        "confirmations_received": decision.confirmations_received,
        "confirmations_remaining": decision.confirmations_remaining,
        "reason": decision.reason,
    }


def sensitive_decision(
    request: SensitiveRequest,
    action_key: str,
    binding: dict[str, object] | None = None,
) -> ActionDecision:
    if confirmation_manager.consume(request.authorization_token, action_key, binding):
        audit_log.record("authorization_consumed", action=action_key, ok=True)
        return ActionDecision(
            allowed=True,
            requires_confirmation=True,
            reason="Deux autorisations serveur reçues pour cette action exacte.",
            confirmations_required=2,
            confirmations_received=2,
        )
    return ActionDecision(
        allowed=False,
        requires_confirmation=True,
        reason=(
            "Action bloquée. Deux autorisations successives sont obligatoires pour "
            "cette action exacte et ses paramètres actuels."
        ),
        confirmations_required=2,
        confirmations_received=0,
    )


def newsletter_cards():
    return [
        card
        for card in action_queue.list()
        if str(card.metadata.get("category") or "") == "newsletter"
    ]


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="API locale de Jarvis Papa",
    )
    install_http_security(app)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return dashboard_html()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "jarvis-papa", "version": __version__}

    @app.get("/api/status")
    def status() -> dict[str, object]:
        return {
            "name": settings.app_name,
            "user_name": settings.user_name,
            "version": __version__,
            "local_only": settings.host in {"127.0.0.1", "localhost", "::1"},
            "security": "server_enforced_two_step_exact_one_time_grants",
            "modules": {
                "mail": "professional_triage_deadlines_and_newsletters",
                "files": file_searcher.backend,
                "desktop": "uia_verified" if windows_uia.available else "safe_actions_ready",
                "voice_input": "disabled_no_microphone",
                "voice_output": "privacy_aware_french_voice",
                "browser": "hardened_playwright" if browser_agent.available else "playwright_missing",
                "ai": "ollama_configured" if local_ai.enabled else "fallback_secretary",
                "memory": "sqlite_habits_ready",
                "tasks": "persistent_prioritized_snooze_ready",
            },
        }

    @app.get("/api/ai/status")
    def ai_status() -> dict[str, object]:
        return local_ai.status()

    @app.post("/api/security/check")
    def security_check(request: SecurityCheckRequest) -> dict[str, object]:
        if request.risk is ActionRisk.READ:
            decision = security_policy.evaluate(ActionRisk.READ)
        else:
            decision = ActionDecision(
                allowed=False,
                requires_confirmation=True,
                reason="Utilise le protocole de double autorisation serveur.",
                confirmations_required=2,
                confirmations_received=0,
            )
        return {"risk": request.risk, **decision_payload(decision)}

    @app.post("/api/confirmations/start")
    def confirmation_start(request: ConfirmationStartRequest) -> dict[str, object]:
        result = confirmation_manager.start(
            request.action_key,
            request.description,
            request.binding,
        )
        audit_log.record(
            "confirmation_started",
            action=request.action_key,
            ok=result.ok,
            detail=request.description,
        )
        return result.to_dict()

    @app.post("/api/confirmations/{challenge_id}/confirm")
    def confirmation_step(challenge_id: str) -> dict[str, object]:
        result = confirmation_manager.confirm(challenge_id)
        audit_log.record(
            "confirmation_step",
            action="double_confirmation",
            ok=result.ok,
            detail=f"step={result.step}; completed={result.completed}",
        )
        return result.to_dict()

    @app.post("/api/speech/event")
    def speech_event(request: SpeechEventRequest) -> dict[str, object]:
        event = SpeechEvent(
            text=request.text,
            importance=request.importance,
            user_initiated=request.user_initiated,
            action_required=request.action_required,
            dedupe_key=request.dedupe_key,
            sensitive=request.sensitive,
            privacy_fallback_text=(
                "Robert, j'ai une information importante à te montrer à l'écran."
                if request.sensitive
                else None
            ),
        )
        decision, spoken = speech_coordinator.handle(event)
        return {
            "should_speak": decision.should_speak,
            "spoken": spoken,
            "reason": decision.reason,
        }

    @app.post("/api/assistant/ask")
    def assistant_ask(request: AssistantRequest) -> dict[str, object]:
        result = jarvis_agent.run(request.text)
        spoken = False
        if result.ok and request.speak and result.answer:
            _, spoken = speech_coordinator.handle(
                SpeechEvent(text=result.answer, user_initiated=True)
            )
        return {**result.to_dict(), "spoken": spoken}

    @app.post("/api/mail/incoming")
    def incoming_mail(request: IncomingMailRequest) -> dict[str, object]:
        mail = IncomingMail(
            message_id=request.message_id,
            header_message_id=request.header_message_id,
            author=request.author,
            subject=request.subject,
            body=request.body,
            folder=request.folder,
            list_unsubscribe=request.list_unsubscribe,
            junk=request.junk,
            date=request.date,
        )
        assessment = mail_assistant.assess(mail)
        card = mail_assistant.create_action_card(mail, assessment)
        spoken = False
        speech_reason = "silent_non_important_mail"
        if card and card.speech_text:
            fallback = (
                "Robert, tu as reçu un message sensible à vérifier. Je te montre le résumé à l'écran."
                if assessment.category == "suspicious"
                else "Robert, tu as reçu un mail important. Je te montre le résumé à l'écran."
            )
            decision, spoken = speech_coordinator.handle(
                SpeechEvent(
                    text=card.speech_text,
                    importance=assessment.importance,
                    action_required=assessment.action_required,
                    dedupe_key=request.header_message_id or f"mail:{request.subject}",
                    sensitive=assessment.sensitive,
                    privacy_fallback_text=fallback,
                )
            )
            speech_reason = decision.reason
        audit_log.record(
            "mail_triaged",
            action=assessment.category,
            ok=True,
            metadata={
                "subject": request.subject[:200],
                "priority": assessment.priority_score,
                "deadline": assessment.deadline_text,
                "confidence": assessment.confidence,
            },
        )
        return {
            "accepted": True,
            "category": assessment.category,
            "noise": assessment.is_noise,
            "importance": assessment.importance.value,
            "action_required": assessment.action_required,
            "summary": assessment.summary,
            "spoken_summary": assessment.spoken_summary,
            "priority_score": assessment.priority_score,
            "confidence": assessment.confidence,
            "deadline_text": assessment.deadline_text,
            "reason": assessment.reason,
            "recommended_action": assessment.recommended_action,
            "card": card.to_dict() if card else None,
            "speech": {"spoken": spoken, "reason": speech_reason},
        }

    @app.get("/api/actions")
    def list_actions() -> list[dict[str, object]]:
        action_queue.unsnooze_due()
        return [
            card.to_dict()
            for card in action_queue.list()
            if str(card.metadata.get("category") or "") != "newsletter"
        ]

    @app.get("/api/newsletters")
    def newsletters() -> dict[str, object]:
        cards = newsletter_cards()
        return {
            "count": len(cards),
            "items": [
                {"id": card.id, "title": card.title, "source": card.source}
                for card in cards[:20]
            ],
        }

    @app.post("/api/newsletters/sort")
    def sort_newsletters(request: SensitiveRequest) -> dict[str, object]:
        cards = newsletter_cards()
        if not cards:
            return {"ok": True, "state": "success", "count": 0, "detail": "Aucune newsletter à ranger."}
        card_ids = [card.id for card in cards]
        decision = sensitive_decision(
            request,
            "mail.sort_newsletters",
            {"card_ids": card_ids},
        )
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        items = [
            {
                "message_id": card.metadata.get("message_id"),
                "header_message_id": card.metadata.get("header_message_id"),
            }
            for card in cards
        ]
        command = thunderbird_commands.enqueue(
            "sort_newsletters",
            {"items": items},
            context={"card_ids": card_ids},
        )
        audit_log.record(
            "command_queued",
            action="mail.sort_newsletters",
            ok=True,
            metadata={"count": len(cards), "command_id": command.id},
        )
        return {
            "ok": True,
            "state": "partial",
            "count": len(cards),
            "command_id": command.id,
            "detail": "J'ai demandé le rangement à Thunderbird. J'attends sa confirmation.",
        }

    @app.post("/api/actions/{card_id}/execute")
    def execute_action(card_id: str, request: ActionExecuteRequest) -> dict[str, object]:
        card = action_queue.get(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Action introuvable.")
        option = next((item for item in card.options if item.id == request.option_id), None)
        if option is None:
            raise HTTPException(status_code=404, detail="Option introuvable.")
        if option.requires_confirmation:
            decision = sensitive_decision(
                request,
                "mail.prepare_reply",
                {"card_id": card_id, "option_id": request.option_id},
            )
            if not decision.allowed:
                return {"ok": False, "state": "failed", **decision_payload(decision)}

        if option.kind is ActionKind.SEARCH_FILES:
            query = str(option.payload.get("query", ""))
            results = [item.to_dict() for item in file_searcher.search(query)]
            memory_store.record_action("search_files", query)
            return {"ok": True, "state": "success", "kind": option.kind, "results": results}
        if option.kind is ActionKind.OPEN_EMAIL:
            command = thunderbird_commands.enqueue(
                "open_message",
                dict(option.payload),
                context={"card_id": card_id},
            )
            return {
                "ok": True,
                "state": "partial",
                "kind": option.kind,
                "command_id": command.id,
                "detail": "J'ai demandé l'ouverture à Thunderbird. J'attends sa confirmation.",
            }
        if option.kind is ActionKind.SEND_REPLY:
            draft = local_ai.draft_reply(
                author=str(card.metadata.get("author") or card.source),
                subject=str(card.metadata.get("subject") or card.title),
                body=str(card.metadata.get("body") or card.summary),
                memory_context=memory_store.context_for(card.source),
            )
            payload = dict(option.payload)
            payload["body"] = draft.body
            command = thunderbird_commands.enqueue(
                "prepare_reply",
                payload,
                context={"card_id": card_id},
            )
            audit_log.record(
                "command_queued",
                action="mail.prepare_reply",
                ok=True,
                metadata={"command_id": command.id, "generated_by_ai": draft.generated_by_ai},
            )
            return {
                "ok": True,
                "state": "partial",
                "kind": option.kind,
                "command_id": command.id,
                "generated_by_ai": draft.generated_by_ai,
                "detail": (
                    "J'ai demandé à Thunderbird de préparer le brouillon. "
                    "Aucun mail n'a été envoyé et j'attends sa confirmation."
                ),
            }
        if option.kind is ActionKind.OPEN_FILE:
            return desktop_controller.open_path(str(option.payload.get("path", ""))).to_dict()
        if option.kind is ActionKind.DISMISS:
            return {"ok": action_queue.snooze(card_id), "state": "success", "kind": option.kind}
        raise HTTPException(status_code=400, detail="Action non gérée.")

    @app.post("/api/actions/{card_id}/attach")
    def prepare_reply_with_attachments(
        card_id: str,
        request: AttachmentReplyRequest,
    ) -> dict[str, object]:
        card = action_queue.get(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Action introuvable.")
        decision = sensitive_decision(
            request,
            "mail.prepare_reply_attachment",
            {"card_id": card_id, "paths": request.paths},
        )
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        leases = []
        try:
            for raw_path in request.paths:
                leases.append(attachment_broker.register(raw_path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Fichier introuvable: {exc}") from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        names = tuple(lease.name for lease in leases)
        draft = local_ai.draft_reply(
            author=str(card.metadata.get("author") or card.source),
            subject=str(card.metadata.get("subject") or card.title),
            body=str(card.metadata.get("body") or card.summary),
            attachment_names=names,
            memory_context=memory_store.context_for(card.source),
        )
        attachments = [
            {
                "url": f"http://127.0.0.1:{settings.port}/api/attachments/{lease.token}",
                "name": lease.name,
                "media_type": lease.media_type,
            }
            for lease in leases
        ]
        command = thunderbird_commands.enqueue(
            "prepare_reply",
            {
                "message_id": card.metadata.get("message_id"),
                "header_message_id": card.metadata.get("header_message_id"),
                "body": draft.body,
                "attachments": attachments,
            },
            context={"card_id": card_id, "attachment_names": list(names)},
        )
        audit_log.record(
            "command_queued",
            action="mail.prepare_reply_attachment",
            ok=True,
            metadata={"command_id": command.id, "attachments": list(names)},
        )
        return {
            "ok": True,
            "state": "partial",
            "command_id": command.id,
            "attachments": list(names),
            "generated_by_ai": draft.generated_by_ai,
            "detail": (
                "J'ai demandé à Thunderbird de préparer le brouillon avec le document. "
                "Aucun mail n'a été envoyé et j'attends sa confirmation."
            ),
        }

    @app.get("/api/attachments/{token}")
    def consume_attachment(token: str) -> FileResponse:
        lease = attachment_broker.consume(token)
        if lease is None:
            raise HTTPException(status_code=404, detail="Pièce jointe expirée ou inconnue.")
        return FileResponse(
            path=lease.path,
            media_type=lease.media_type,
            filename=lease.name,
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/actions/{card_id}/snooze")
    def snooze_action(card_id: str, request: SnoozeRequest) -> dict[str, object]:
        decision = sensitive_decision(
            request,
            "actions.snooze",
            {"card_id": card_id, "hours": request.hours},
        )
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        ok = action_queue.snooze(card_id, int(request.hours * 3600))
        audit_log.record(
            "task_snoozed",
            action="actions.snooze",
            ok=ok,
            metadata={"card_id": card_id, "hours": request.hours},
        )
        return {
            "ok": ok,
            "state": "success" if ok else "failed",
            "detail": f"Je te le remontrerai dans environ {request.hours:g} heure(s).",
        }

    @app.delete("/api/actions/{card_id}")
    def dismiss_action(card_id: str, request: SensitiveRequest) -> dict[str, object]:
        decision = sensitive_decision(
            request,
            "actions.dismiss",
            {"card_id": card_id},
        )
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        ok = action_queue.remove(card_id)
        audit_log.record("task_removed", action="actions.dismiss", ok=ok, metadata={"card_id": card_id})
        return {"ok": ok, "state": "success" if ok else "failed"}

    @app.get("/api/files/search")
    def search_files(
        q: str = Query(min_length=1, max_length=300),
        limit: int = Query(default=12, ge=1, le=30),
    ) -> dict[str, object]:
        results = file_searcher.search(q, limit=limit)
        return {"backend": file_searcher.backend, "results": [item.to_dict() for item in results]}

    @app.post("/api/files/open")
    def open_file(request: OpenPathRequest) -> dict[str, object]:
        return desktop_controller.open_path(request.path).to_dict()

    @app.post("/api/desktop/start")
    def start_app(request: StartAppRequest) -> dict[str, object]:
        return desktop_controller.start_app(request.app).to_dict()

    @app.get("/api/windows/windows")
    def windows_list() -> dict[str, object]:
        return windows_uia.list_windows().to_dict()

    @app.post("/api/windows/inspect")
    def windows_inspect(request: UIAInspectRequest) -> dict[str, object]:
        return windows_uia.inspect_window(request.window_title).to_dict()

    @app.post("/api/windows/invoke")
    def windows_invoke(request: UIAInvokeRequest) -> dict[str, object]:
        binding = {
            "window_title": request.window_title,
            "control_name": request.control_name,
            "control_type": request.control_type,
        }
        decision = sensitive_decision(request, "windows.invoke", binding)
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        result = windows_uia.invoke_control(
            window_title=request.window_title,
            control_name=request.control_name,
            control_type=request.control_type,
        )
        audit_log.record("windows_action", action="windows.invoke", ok=result.ok, detail=result.detail)
        return result.to_dict()

    @app.post("/api/windows/text")
    def windows_set_text(request: UIASetTextRequest) -> dict[str, object]:
        binding = {
            "window_title": request.window_title,
            "control_name": request.control_name,
            "text": request.text,
        }
        decision = sensitive_decision(request, "windows.set_text", binding)
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        result = windows_uia.set_text(
            window_title=request.window_title,
            control_name=request.control_name,
            text=request.text,
        )
        audit_log.record("windows_action", action="windows.set_text", ok=result.ok, detail=result.detail)
        return result.to_dict()

    @app.post("/api/browser/search")
    def browser_search(request: WebSearchRequest) -> dict[str, object]:
        return desktop_controller.search_web(request.query).to_dict()

    @app.post("/api/browser/read")
    def browser_read(request: BrowserReadRequest) -> dict[str, object]:
        return browser_agent.read_url(request.url).to_dict()

    @app.post("/api/browser/download")
    def browser_download(request: BrowserDownloadRequest) -> dict[str, object]:
        binding = {"url": request.url, "link_text": request.link_text}
        decision = sensitive_decision(request, "browser.download", binding)
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        result = browser_agent.download_by_text(request.url, request.link_text)
        audit_log.record("browser_action", action="browser.download", ok=result.ok, detail=result.detail)
        return result.to_dict()

    @app.post("/api/memory/remember")
    def remember(request: RememberRequest) -> dict[str, object]:
        binding = {
            "category": request.category,
            "key": request.key,
            "value": request.value,
        }
        decision = sensitive_decision(request, "memory.remember", binding)
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        item = memory_store.remember(request.category, request.key, request.value)
        audit_log.record(
            "memory_updated",
            action="memory.remember",
            ok=True,
            metadata={"category": request.category, "key": request.key},
        )
        return {"ok": True, "state": "success", "memory": item.to_dict()}

    @app.get("/api/memory/recall")
    def recall(q: str = Query(min_length=1, max_length=500)) -> dict[str, object]:
        return {"results": [item.to_dict() for item in memory_store.recall(q)]}

    @app.get("/api/memory/habits")
    def habits() -> dict[str, object]:
        return {"results": [habit.to_dict() for habit in memory_store.habits()]}

    @app.get("/api/audit/recent")
    def audit_recent(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, object]:
        return {"results": audit_log.recent(limit)}

    @app.get("/api/thunderbird/commands")
    def list_thunderbird_commands() -> list[dict[str, object]]:
        return [command.to_dict() for command in thunderbird_commands.pending()]

    @app.get("/api/thunderbird/commands/{command_id}")
    def thunderbird_command(command_id: str) -> dict[str, object]:
        command = thunderbird_commands.get(command_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Commande inconnue.")
        return command.to_dict()

    @app.get("/api/thunderbird/history")
    def thunderbird_history() -> list[dict[str, object]]:
        return [command.to_dict() for command in thunderbird_commands.recent()]

    @app.post("/api/thunderbird/commands/{command_id}/ack")
    def acknowledge_thunderbird_command(
        command_id: str,
        request: ThunderbirdAckRequest,
    ) -> dict[str, object]:
        command = thunderbird_commands.get(command_id)
        if command is None:
            return {"ok": False, "state": "failed", "detail": "Commande inconnue."}
        updated = thunderbird_commands.acknowledge(
            command_id,
            ok=request.ok,
            error=request.error,
        )
        if not updated:
            return {
                "ok": False,
                "state": "failed",
                "detail": "Accusé de réception non enregistré.",
            }

        if request.ok and command.kind == "sort_newsletters":
            card_ids = command.context.get("card_ids")
            if isinstance(card_ids, list):
                action_queue.remove_many([str(item) for item in card_ids])
                memory_store.record_action("sort_newsletters", str(len(card_ids)))
        elif not request.ok:
            detail = request.error or "Thunderbird n'a pas pu terminer l'action."
            action_queue.create(
                title="Une action Thunderbird a échoué",
                summary=f"Jarvis n'a rien considéré comme réussi. {detail[:220]}",
                source="Jarvis",
                importance=SpeechImportance.HIGH.value,
                speech_text=(
                    "Robert, une action dans Thunderbird a échoué. Je n'ai rien considéré "
                    "comme terminé. Regarde l'écran pour le détail."
                ),
                metadata={
                    "category": "system_error",
                    "priority_score": 95,
                    "command_id": command_id,
                    "recommended_action": "Ouvrir Thunderbird et vérifier avant de réessayer.",
                },
                priority_score=95,
                dedupe_key=f"command-error:{command_id}",
            )
        audit_log.record(
            "command_ack",
            action=command.kind,
            ok=request.ok,
            detail=request.error or "Commande confirmée par Thunderbird.",
            metadata={"command_id": command_id},
        )
        return {
            "ok": True,
            "state": "success" if request.ok else "failed",
            "status": "succeeded" if request.ok else "failed",
        }

    @app.post("/api/thunderbird/commands/{command_id}/retry")
    def retry_thunderbird_command(
        command_id: str,
        request: SensitiveRequest,
    ) -> dict[str, object]:
        decision = sensitive_decision(
            request,
            "thunderbird.retry",
            {"command_id": command_id},
        )
        if not decision.allowed:
            return {"ok": False, "state": "failed", **decision_payload(decision)}
        ok = thunderbird_commands.retry(command_id)
        audit_log.record(
            "command_retry",
            action="thunderbird.retry",
            ok=ok,
            metadata={"command_id": command_id},
        )
        return {"ok": ok, "state": "partial" if ok else "failed"}

    return app
