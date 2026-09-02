from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jarvis_papa.audit import audit_log
from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.memory_center import memory_center

router = APIRouter(prefix="/api/memory-center", tags=["memory-center"])


class MemoryMutationRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=1, max_length=160)
    value: str = Field(default="", max_length=6000)
    authorization_token: str = Field(default="", max_length=300)


class ProcedureMutationRequest(BaseModel):
    procedure_id: str = Field(min_length=1, max_length=100)
    summary: str = Field(default="", max_length=300)
    authorization_token: str = Field(default="", max_length=300)


def _consume(token: str, action_key: str, binding: dict[str, object]) -> bool:
    ok = confirmation_manager.consume(token, action_key, binding)
    audit_log.record(
        "authorization_consumed",
        action=action_key,
        ok=ok,
        metadata={"binding_keys": sorted(binding)},
    )
    return ok


@router.get("")
def list_memory_center() -> dict[str, object]:
    return memory_center.list(limit=100)


@router.post("/update/plan")
def update_memory_plan(request: MemoryMutationRequest) -> dict[str, object]:
    return memory_center.update_plan(request.category, request.key, request.value)


@router.post("/update")
def update_memory(request: MemoryMutationRequest) -> dict[str, object]:
    plan = memory_center.update_plan(request.category, request.key, request.value)
    binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
    if not _consume(request.authorization_token, "memory.update", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Modification bloquée : deux autorisations exactes sont obligatoires.",
        }
    result = memory_center.update(request.category, request.key, request.value)
    audit_log.record("memory_center_update", action="memory.update", ok=bool(result.get("ok")))
    return result


@router.post("/forget/plan")
def forget_memory_plan(request: MemoryMutationRequest) -> dict[str, object]:
    return memory_center.forget_plan(request.category, request.key)


@router.post("/forget")
def forget_memory(request: MemoryMutationRequest) -> dict[str, object]:
    plan = memory_center.forget_plan(request.category, request.key)
    binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
    if not _consume(request.authorization_token, "memory.forget", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Oubli bloqué : deux autorisations exactes sont obligatoires.",
        }
    result = memory_center.forget(request.category, request.key)
    audit_log.record("memory_center_forget", action="memory.forget", ok=bool(result.get("ok")))
    return result


@router.post("/procedure/disable/plan")
def procedure_disable_plan(request: ProcedureMutationRequest) -> dict[str, object]:
    return memory_center.procedure_disable_plan(request.procedure_id, request.summary)


@router.post("/procedure/disable")
def procedure_disable(request: ProcedureMutationRequest) -> dict[str, object]:
    plan = memory_center.procedure_disable_plan(request.procedure_id, request.summary)
    binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
    if not _consume(request.authorization_token, "memory.procedure.disable", binding):
        return {
            "ok": False,
            "state": "failed",
            "detail": "Désactivation bloquée : deux autorisations exactes sont obligatoires.",
        }
    result = memory_center.procedure_disable(request.procedure_id)
    audit_log.record(
        "memory_procedure_disable",
        action="memory.procedure.disable",
        ok=bool(result.get("ok")),
    )
    return result
