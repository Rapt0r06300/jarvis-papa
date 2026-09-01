from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.evaluation import improvement_lab
from jarvis_papa.governance import circuit_breakers, kill_switch
from jarvis_papa.knowledge import local_document_rag
from jarvis_papa.proactivity import briefing_service, proactive_events
from jarvis_papa.procedural_memory import procedural_memory
from jarvis_papa.pronunciation import pronunciation_lexicon
from jarvis_papa.runtime_intelligence import (
    reliability_map,
    resource_governor,
    windows_isolation,
)
from jarvis_papa.tracing import trace_store
from jarvis_papa.transactions import transaction_journal

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class KillRequest(BaseModel):
    reason: str = Field(default="Arrêt demandé par l'utilisateur.", max_length=500)


class AuthorizationRequest(BaseModel):
    authorization_token: str = Field(default="", max_length=300)


class ProcedureCandidateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=600)
    steps: list[str] = Field(min_length=2, max_length=20)
    evidence_count: int = Field(ge=2, le=1000)
    success_rate: float = Field(ge=0.0, le=1.0)
    authorization_token: str = Field(default="", max_length=300)


class PronunciationRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    pronunciation: str = Field(min_length=1, max_length=160)
    authorization_token: str = Field(default="", max_length=300)


class RollbackRequest(BaseModel):
    authorization_token: str = Field(default="", max_length=300)


@router.get("/status")
def intelligence_status() -> dict[str, object]:
    return {
        "ok": True,
        "kill_switch": kill_switch.status(),
        "circuits": circuit_breakers.snapshot(),
        "resources": resource_governor.snapshot().to_dict(),
        "procedural_memory": procedural_memory.status(),
        "tracing": trace_store.aggregate(),
        "windows_isolation": windows_isolation.status(),
    }


@router.get("/briefing")
def briefing() -> dict[str, object]:
    return briefing_service.current(limit=3)


@router.get("/events")
def events(after: int = 0) -> dict[str, object]:
    return {"events": [item.to_dict() for item in proactive_events.after(max(0, int(after)))]}


@router.post("/knowledge/search")
def knowledge_search(request: SearchRequest) -> dict[str, object]:
    hits = local_document_rag.search(request.query, limit=8)
    return {
        "ok": True,
        "results": [item.to_dict() for item in hits],
        "detail": f"{len(hits)} extrait(s) local(aux) avec provenance.",
    }


@router.get("/procedures")
def procedures() -> dict[str, object]:
    return {"items": [item.to_dict() for item in procedural_memory.list(limit=50)]}


@router.post("/procedures/plan")
def procedure_plan(request: ProcedureCandidateRequest) -> dict[str, object]:
    candidate = procedural_memory.candidate_from_trace(
        key=request.key,
        summary=request.summary,
        steps=request.steps,
        evidence_count=request.evidence_count,
        success_rate=request.success_rate,
    )
    if candidate is None:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Cette procédure n'a pas encore assez de preuves pour être proposée.",
        }
    binding = candidate.to_dict()
    return {
        "ok": True,
        "action_key": "memory.procedure.promote",
        "binding": binding,
        "candidate": binding,
        "description": (
            "Ajouter cette méthode aux procédures approuvées de Jarvis. "
            "Elle restera désactivable et ne contournera jamais les confirmations."
        ),
    }


@router.post("/procedures/promote")
def procedure_promote(request: ProcedureCandidateRequest) -> dict[str, object]:
    candidate = procedural_memory.candidate_from_trace(
        key=request.key,
        summary=request.summary,
        steps=request.steps,
        evidence_count=request.evidence_count,
        success_rate=request.success_rate,
    )
    if candidate is None:
        return {"ok": False, "state": "failed", "detail": "Candidat insuffisamment prouvé."}
    binding = candidate.to_dict()
    authorized = confirmation_manager.consume(
        request.authorization_token,
        "memory.procedure.promote",
        binding,
    )
    if not authorized:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Ajout bloqué : deux autorisations exactes sont obligatoires.",
        }
    stored = procedural_memory.promote(candidate)
    return {
        "ok": True,
        "state": "success",
        "procedure": stored.to_dict(),
        "detail": "La procédure a été ajoutée à la mémoire procédurale approuvée.",
    }


@router.get("/traces/summary")
def traces_summary() -> dict[str, object]:
    return trace_store.aggregate()


@router.get("/evaluation")
def evaluation() -> dict[str, object]:
    return improvement_lab.security_suite()


@router.get("/reliability")
def reliability() -> dict[str, object]:
    return reliability_map.snapshot()


@router.get("/resources")
def resources() -> dict[str, object]:
    return resource_governor.snapshot().to_dict()


@router.get("/isolation")
def isolation() -> dict[str, object]:
    return windows_isolation.status()


@router.post("/kill-switch")
def activate_kill_switch(request: KillRequest) -> dict[str, object]:
    return {
        "ok": True,
        "state": "success",
        "kill_switch": kill_switch.activate(request.reason),
        "detail": "Arrêt global activé. Les nouvelles modifications sont bloquées.",
    }


@router.get("/kill-switch/clear-plan")
def clear_kill_switch_plan() -> dict[str, object]:
    return {
        "ok": True,
        "action_key": "jarvis.kill_switch.clear",
        "binding": {},
        "description": "Réautoriser Jarvis à effectuer des modifications après l'arrêt global.",
    }


@router.post("/kill-switch/clear")
def clear_kill_switch(request: AuthorizationRequest) -> dict[str, object]:
    authorized = confirmation_manager.consume(
        request.authorization_token,
        "jarvis.kill_switch.clear",
        {},
    )
    if not authorized:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Réactivation bloquée : deux autorisations exactes sont obligatoires.",
        }
    return {
        "ok": True,
        "state": "success",
        "kill_switch": kill_switch.clear(),
        "detail": "Jarvis peut de nouveau effectuer des actions autorisées.",
    }


@router.post("/pronunciation/plan")
def pronunciation_plan(request: PronunciationRequest) -> dict[str, object]:
    return {"ok": True, **pronunciation_lexicon.preview_update(request.source, request.pronunciation)}


@router.post("/pronunciation")
def pronunciation_update(request: PronunciationRequest) -> dict[str, object]:
    plan = pronunciation_lexicon.preview_update(request.source, request.pronunciation)
    binding = plan["binding"] if isinstance(plan.get("binding"), dict) else {}
    authorized = confirmation_manager.consume(
        request.authorization_token,
        "voice.pronunciation.update",
        binding,
    )
    if not authorized:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Prononciation non modifiée : deux autorisations sont obligatoires.",
        }
    ok = pronunciation_lexicon.update(request.source, request.pronunciation)
    return {
        "ok": ok,
        "state": "success" if ok else "failed",
        "detail": "Prononciation enregistrée." if ok else "La prononciation n'a pas été enregistrée.",
    }


@router.get("/transactions")
def transactions() -> dict[str, object]:
    return {"items": [item.to_dict() for item in transaction_journal.recent(limit=30)]}


@router.get("/transactions/{transaction_id}/rollback-plan")
def rollback_plan(transaction_id: str) -> dict[str, object]:
    record = transaction_journal.latest(transaction_id)
    if record is None:
        return {"ok": False, "state": "failed", "detail": "Transaction introuvable."}
    binding = {"transaction_id": transaction_id, "action_key": record.action_key}
    return {
        "ok": True,
        "action_key": "transaction.rollback",
        "binding": binding,
        "description": "Annuler cette modification lorsque Jarvis sait la restaurer et la vérifier.",
    }


@router.post("/transactions/{transaction_id}/rollback")
def rollback(transaction_id: str, request: RollbackRequest) -> dict[str, object]:
    record = transaction_journal.latest(transaction_id)
    if record is None:
        return {"ok": False, "state": "failed", "detail": "Transaction introuvable."}
    binding = {"transaction_id": transaction_id, "action_key": record.action_key}
    authorized = confirmation_manager.consume(
        request.authorization_token,
        "transaction.rollback",
        binding,
    )
    if not authorized:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Rollback bloqué : deux autorisations exactes sont obligatoires.",
        }
    return transaction_journal.rollback(transaction_id)
