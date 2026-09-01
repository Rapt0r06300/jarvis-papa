from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from jarvis_papa import __version__
from jarvis_papa.actions import ActionKind, action_queue
from jarvis_papa.agent import jarvis_agent
from jarvis_papa.ai import local_ai
from jarvis_papa.attachments import attachment_broker
from jarvis_papa.browser import browser_agent
from jarvis_papa.config import settings
from jarvis_papa.dashboard import dashboard_html
from jarvis_papa.desktop import desktop_controller
from jarvis_papa.files import file_searcher
from jarvis_papa.mail import IncomingMail, mail_assistant
from jarvis_papa.memory import memory_store
from jarvis_papa.security import ActionDecision, ActionRisk, security_policy
from jarvis_papa.speech import SpeechEvent, SpeechImportance, speech_coordinator
from jarvis_papa.thunderbird import thunderbird_commands
from jarvis_papa.windows_automation import windows_uia


class SensitiveRequest(BaseModel):
    confirmations: int = Field(default=0, ge=0, le=2)
    confirmed: bool = False


class SecurityCheckRequest(SensitiveRequest):
    risk: ActionRisk


class SpeechEventRequest(BaseModel):
    text: str
    importance: SpeechImportance = SpeechImportance.NORMAL
    user_initiated: bool = False
    action_required: bool = False
    dedupe_key: str | None = None


class IncomingMailRequest(BaseModel):
    message_id: int | None = None
    header_message_id: str | None = None
    author: str = ""
    subject: str = ""
    body: str = ""
    folder: str = "Inbox"


class ActionExecuteRequest(SensitiveRequest):
    option_id: str


class AttachmentReplyRequest(SensitiveRequest):
    paths: list[str] = Field(min_length=1, max_length=5)


class OpenPathRequest(BaseModel):
    path: str


class StartAppRequest(BaseModel):
    app: str


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


def decision_payload(decision: ActionDecision) -> dict[str, object]:
    return {
        "allowed": decision.allowed,
        "requires_confirmation": decision.requires_confirmation,
        "confirmations_required": decision.confirmations_required,
        "confirmations_received": decision.confirmations_received,
        "confirmations_remaining": decision.confirmations_remaining,
        "reason": decision.reason,
    }


def sensitive_decision(request: SensitiveRequest) -> ActionDecision:
    return security_policy.evaluate(
        ActionRisk.WRITE,
        confirmations=request.confirmations,
        confirmed=request.confirmed,
    )


def newsletter_cards():
    return [
        card
        for card in action_queue.list()
        if str(card.metadata.get("category") or "") == "newsletter"
    ]


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=__version__, description="API locale de Jarvis Papa")

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
            "local_only": settings.host in {"127.0.0.1", "localhost"},
            "security": "two_explicit_confirmations_for_changes",
            "modules": {
                "mail": "important_summaries_and_newsletter_sorting",
                "files": file_searcher.backend,
                "desktop": "uia_ready" if windows_uia.available else "safe_actions_ready",
                "voice_input": "disabled_no_microphone",
                "voice_output": "important_mail_summaries_ready",
                "browser": "playwright_ready" if browser_agent.available else "playwright_missing",
                "ai": "ollama_configured" if local_ai.enabled else "disabled",
                "memory": "sqlite_habits_ready",
            },
        }

    @app.get("/api/ai/status")
    def ai_status() -> dict[str, object]:
        return local_ai.status()

    @app.post("/api/security/check")
    def security_check(request: SecurityCheckRequest) -> dict[str, object]:
        decision = security_policy.evaluate(
            request.risk,
            confirmations=request.confirmations,
            confirmed=request.confirmed,
        )
        return {"risk": request.risk, **decision_payload(decision)}

    @app.post("/api/speech/event")
    def speech_event(request: SpeechEventRequest) -> dict[str, object]:
        event = SpeechEvent(
            text=request.text,
            importance=request.importance,
            user_initiated=request.user_initiated,
            action_required=request.action_required,
            dedupe_key=request.dedupe_key,
        )
        decision, spoken = speech_coordinator.handle(event)
        return {"should_speak": decision.should_speak, "spoken": spoken, "reason": decision.reason}

    @app.post("/api/assistant/ask")
    def assistant_ask(request: AssistantRequest) -> dict[str, object]:
        result = jarvis_agent.run(request.text)
        spoken = False
        if result.ok and request.speak and result.answer:
            _, spoken = speech_coordinator.handle(SpeechEvent(text=result.answer, user_initiated=True))
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
        )
        assessment = mail_assistant.assess(mail)
        card = mail_assistant.create_action_card(mail, assessment)
        spoken = False
        speech_reason = "silent_non_important_mail"
        if card and card.speech_text:
            decision, spoken = speech_coordinator.handle(
                SpeechEvent(
                    text=card.speech_text,
                    importance=assessment.importance,
                    action_required=assessment.action_required,
                    dedupe_key=request.header_message_id or f"mail:{request.subject}",
                )
            )
            speech_reason = decision.reason
        return {
            "accepted": True,
            "category": assessment.category,
            "noise": assessment.is_noise,
            "importance": assessment.importance.value,
            "action_required": assessment.action_required,
            "summary": assessment.summary,
            "spoken_summary": assessment.spoken_summary,
            "card": card.to_dict() if card else None,
            "speech": {"spoken": spoken, "reason": speech_reason},
        }

    @app.get("/api/actions")
    def list_actions() -> list[dict[str, object]]:
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
            "items": [{"id": card.id, "title": card.title, "source": card.source} for card in cards[:20]],
        }

    @app.post("/api/newsletters/sort")
    def sort_newsletters(request: SensitiveRequest) -> dict[str, object]:
        cards = newsletter_cards()
        if not cards:
            return {"ok": True, "count": 0, "detail": "Aucune newsletter à ranger."}
        decision = sensitive_decision(request)
        if not decision.allowed:
            return {"ok": False, **decision_payload(decision)}
        items = [
            {
                "message_id": card.metadata.get("message_id"),
                "header_message_id": card.metadata.get("header_message_id"),
            }
            for card in cards
        ]
        command = thunderbird_commands.enqueue("sort_newsletters", {"items": items})
        for card in cards:
            action_queue.remove(card.id)
        memory_store.record_action("sort_newsletters", str(len(cards)))
        return {"ok": True, "count": len(cards), "command_id": command.id}

    @app.post("/api/actions/{card_id}/execute")
    def execute_action(card_id: str, request: ActionExecuteRequest) -> dict[str, object]:
        card = action_queue.get(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Action introuvable.")
        option = next((item for item in card.options if item.id == request.option_id), None)
        if option is None:
            raise HTTPException(status_code=404, detail="Option introuvable.")
        if option.requires_confirmation:
            decision = sensitive_decision(request)
            if not decision.allowed:
                return {"ok": False, **decision_payload(decision)}

        if option.kind is ActionKind.SEARCH_FILES:
            query = str(option.payload.get("query", ""))
            results = [item.to_dict() for item in file_searcher.search(query)]
            memory_store.record_action("search_files", query)
            return {"ok": True, "kind": option.kind, "results": results}
        if option.kind is ActionKind.OPEN_EMAIL:
            command = thunderbird_commands.enqueue("open_message", dict(option.payload))
            return {"ok": True, "kind": option.kind, "command_id": command.id}
        if option.kind is ActionKind.SEND_REPLY:
            draft = local_ai.draft_reply(
                author=str(card.metadata.get("author") or card.source),
                subject=str(card.metadata.get("subject") or card.title),
                body=str(card.metadata.get("body") or card.summary),
                memory_context=memory_store.context_for(card.source),
            )
            payload = dict(option.payload)
            payload["body"] = draft.body
            command = thunderbird_commands.enqueue("prepare_reply", payload)
            return {
                "ok": True,
                "kind": option.kind,
                "command_id": command.id,
                "generated_by_ai": draft.generated_by_ai,
                "detail": "Brouillon préparé. Aucun mail n'a été envoyé.",
            }
        if option.kind is ActionKind.OPEN_FILE:
            return desktop_controller.open_path(str(option.payload.get("path", ""))).to_dict()
        if option.kind is ActionKind.DISMISS:
            return {"ok": action_queue.remove(card_id), "kind": option.kind}
        raise HTTPException(status_code=400, detail="Action non gérée.")

    @app.post("/api/actions/{card_id}/attach")
    def prepare_reply_with_attachments(card_id: str, request: AttachmentReplyRequest) -> dict[str, object]:
        card = action_queue.get(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Action introuvable.")
        decision = sensitive_decision(request)
        if not decision.allowed:
            return {"ok": False, **decision_payload(decision)}
        leases = []
        try:
            for raw_path in request.paths:
                leases.append(attachment_broker.register(raw_path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Fichier introuvable: {exc}") from exc
        names = tuple(lease.name for lease in leases)
        draft = local_ai.draft_reply(
            author=str(card.metadata.get("author") or card.source),
            subject=str(card.metadata.get("subject") or card.title),
            body=str(card.metadata.get("body") or card.summary),
            attachment_names=names,
            memory_context=memory_store.context_for(card.source),
        )
        host = "127.0.0.1" if settings.host in {"127.0.0.1", "localhost"} else settings.host
        attachments = [
            {
                "url": f"http://{host}:{settings.port}/api/attachments/{lease.token}",
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
        )
        return {
            "ok": True,
            "command_id": command.id,
            "attachments": list(names),
            "generated_by_ai": draft.generated_by_ai,
            "detail": "Brouillon préparé avec pièce jointe. Aucun mail n'a été envoyé.",
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

    @app.delete("/api/actions/{card_id}")
    def dismiss_action(card_id: str) -> dict[str, bool]:
        return {"ok": action_queue.remove(card_id)}

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
        decision = sensitive_decision(request)
        if not decision.allowed:
            return {"ok": False, **decision_payload(decision)}
        return windows_uia.invoke_control(
            window_title=request.window_title,
            control_name=request.control_name,
            control_type=request.control_type,
        ).to_dict()

    @app.post("/api/windows/text")
    def windows_set_text(request: UIASetTextRequest) -> dict[str, object]:
        decision = sensitive_decision(request)
        if not decision.allowed:
            return {"ok": False, **decision_payload(decision)}
        return windows_uia.set_text(
            window_title=request.window_title,
            control_name=request.control_name,
            text=request.text,
        ).to_dict()

    @app.post("/api/browser/search")
    def browser_search(request: WebSearchRequest) -> dict[str, object]:
        return desktop_controller.search_web(request.query).to_dict()

    @app.post("/api/browser/read")
    def browser_read(request: BrowserReadRequest) -> dict[str, object]:
        return browser_agent.read_url(request.url).to_dict()

    @app.post("/api/browser/download")
    def browser_download(request: BrowserDownloadRequest) -> dict[str, object]:
        decision = sensitive_decision(request)
        if not decision.allowed:
            return {"ok": False, **decision_payload(decision)}
        return browser_agent.download_by_text(request.url, request.link_text).to_dict()

    @app.post("/api/memory/remember")
    def remember(request: RememberRequest) -> dict[str, object]:
        decision = sensitive_decision(request)
        if not decision.allowed:
            return {"ok": False, **decision_payload(decision)}
        item = memory_store.remember(request.category, request.key, request.value)
        return {"ok": True, "memory": item.to_dict()}

    @app.get("/api/memory/recall")
    def recall(q: str = Query(min_length=1, max_length=500)) -> dict[str, object]:
        return {"results": [item.to_dict() for item in memory_store.recall(q)]}

    @app.get("/api/memory/habits")
    def habits() -> dict[str, object]:
        return {"results": [habit.to_dict() for habit in memory_store.habits()]}

    @app.get("/api/thunderbird/commands")
    def list_thunderbird_commands() -> list[dict[str, object]]:
        return [command.to_dict() for command in thunderbird_commands.pending()]

    @app.post("/api/thunderbird/commands/{command_id}/ack")
    def acknowledge_thunderbird_command(command_id: str) -> dict[str, bool]:
        return {"ok": thunderbird_commands.acknowledge(command_id)}

    return app
