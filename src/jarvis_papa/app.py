"""Jarvis Papa local application service."""

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import jarvis_papa.agent as agent_module
import jarvis_papa.mail_intelligence as mail_intelligence_module
import jarvis_papa.routes as routes_module
import jarvis_papa.tooling as tooling_module
from jarvis_papa.advanced_routes import router as advanced_router
from jarvis_papa.audit import audit_log
from jarvis_papa.browser_workflow_routes import router as browser_workflow_router
from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.conversation import conversation_manager
from jarvis_papa.dashboard_secure import dashboard_html as secure_dashboard_html
from jarvis_papa.diagnostics import diagnostics
from jarvis_papa.intelligence_routes import router as intelligence_router
from jarvis_papa.mail_intelligence import intelligent_mail_assistant
from jarvis_papa.memory_semantic import semantic_memory_store
from jarvis_papa.speech import SpeechEvent, speech_coordinator
from jarvis_papa.thunderbird import thunderbird_bridge_state
from jarvis_papa.thunderbird_probe_routes import router as thunderbird_probe_router
from jarvis_papa.voice import voice_service

routes_module.mail_assistant = intelligent_mail_assistant
routes_module.memory_store = semantic_memory_store
routes_module.dashboard_html = secure_dashboard_html
agent_module.memory_store = semantic_memory_store
tooling_module.memory_store = semantic_memory_store
mail_intelligence_module.memory_store = semantic_memory_store

app = routes_module.create_app()
app.include_router(advanced_router)
app.include_router(browser_workflow_router)
app.include_router(thunderbird_probe_router)
app.include_router(intelligence_router)
voice_service.prewarm_async()


class VoicePreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)


class ThunderbirdHeartbeatRequest(BaseModel):
    source: str = Field(default="native_host", min_length=1, max_length=80)
    pid: int | None = Field(default=None, ge=1)


class ConversationTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    conversation_id: str | None = Field(default=None, min_length=8, max_length=80)
    request_id: str | None = Field(default=None, min_length=8, max_length=80)
    speak: bool = True


class ConversationCancelRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)


class ConversationResetRequest(BaseModel):
    authorization_token: str = Field(default="", max_length=300)


@app.get("/ready")
def readiness() -> JSONResponse:
    report = diagnostics.run()
    return JSONResponse(status_code=200 if report["ready"] else 503, content=report)


@app.get("/api/diagnostics")
def diagnostic_report() -> dict[str, object]:
    return diagnostics.run()


@app.post("/api/conversation/turn")
def conversation_turn(request: ConversationTurnRequest) -> dict[str, object]:
    turn = conversation_manager.turn(
        request.text,
        conversation_id=request.conversation_id,
        request_id=request.request_id,
    )
    spoken = False
    if request.speak and turn.answer and turn.final_state != "cancelled":
        _, spoken = speech_coordinator.handle(SpeechEvent(text=turn.answer, user_initiated=True))
    return {**turn.to_dict(), "spoken": spoken}


@app.post("/api/conversation/{conversation_id}/cancel")
def conversation_cancel(
    conversation_id: str,
    request: ConversationCancelRequest,
) -> dict[str, object]:
    cancelled = conversation_manager.cancel(conversation_id, request.request_id)
    return {
        "ok": cancelled,
        "detail": (
            "J'arrête cette demande."
            if cancelled
            else "Cette demande n'est plus active ou n'existe pas."
        ),
    }


@app.get("/api/conversation/{conversation_id}/reset-plan")
def conversation_reset_plan(conversation_id: str) -> dict[str, object]:
    binding = {"conversation_id": conversation_id}
    return {
        "ok": True,
        "action_key": "conversation.reset",
        "binding": binding,
        "description": "Supprimer l'historique local de cette conversation.",
    }


@app.delete("/api/conversation/{conversation_id}")
def conversation_reset(
    conversation_id: str,
    request: ConversationResetRequest,
) -> dict[str, object]:
    binding = {"conversation_id": conversation_id}
    authorized = confirmation_manager.consume(
        request.authorization_token,
        "conversation.reset",
        binding,
    )
    audit_log.record(
        "authorization_consumed",
        action="conversation.reset",
        ok=authorized,
        metadata=binding,
    )
    if not authorized:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Suppression bloquée : deux autorisations exactes sont obligatoires.",
        }
    deleted = conversation_manager.reset(conversation_id)
    audit_log.record(
        "conversation_reset",
        action="conversation.reset",
        ok=deleted,
        metadata=binding,
    )
    return {
        "ok": deleted,
        "state": "success" if deleted else "failed",
        "detail": (
            "L'historique local de cette conversation a été supprimé."
            if deleted
            else "Aucun historique local n'a été supprimé."
        ),
    }


@app.post("/api/thunderbird/bridge/heartbeat")
def thunderbird_bridge_heartbeat(request: ThunderbirdHeartbeatRequest) -> dict[str, object]:
    thunderbird_bridge_state.mark_seen(request.source, request.pid)
    return {"ok": True, **thunderbird_bridge_state.snapshot()}


@app.get("/api/thunderbird/bridge/status")
def thunderbird_bridge_status() -> dict[str, object]:
    return thunderbird_bridge_state.snapshot()


@app.get("/api/voice/status")
def voice_status() -> dict[str, object]:
    return voice_service.status()


@app.get("/api/voice/events")
def voice_events(after: int = Query(default=0, ge=0)) -> dict[str, object]:
    return {"events": voice_service.events.after(after)}


@app.post("/api/voice/preview")
def voice_preview(request: VoicePreviewRequest) -> dict[str, object]:
    return voice_service.speak(request.text).to_dict()


@app.get("/api/voice/audio/{file_name}")
def voice_audio(file_name: str) -> FileResponse:
    path = voice_service.resolve_audio(file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio introuvable.")
    media_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(path=path, media_type=media_type, filename=path.name)
