from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jarvis_papa.audit import audit_log
from jarvis_papa.browser_workflow import browser_workflow
from jarvis_papa.confirmations import confirmation_manager

router = APIRouter(prefix="/api/advanced/browser", tags=["advanced-browser"])


class BrowserMultiStepRequest(BaseModel):
    url: str = Field(min_length=8, max_length=3000)
    steps: list[dict[str, object]] = Field(min_length=1, max_length=20)
    verify_text: str = Field(default="", max_length=500)
    session_name: str = Field(default="default", max_length=60)
    authorization_token: str = Field(default="", max_length=300)


@router.post("/workflow")
def browser_multistep(request: BrowserMultiStepRequest) -> dict[str, object]:
    binding = {
        "url": request.url,
        "steps": request.steps,
        "verify_text": request.verify_text,
        "session_name": request.session_name,
    }
    authorized = confirmation_manager.consume(
        request.authorization_token,
        "browser.execute_multistep",
        binding,
    )
    audit_log.record(
        "authorization_consumed",
        action="browser.execute_multistep",
        ok=authorized,
    )
    if not authorized:
        return {
            "ok": False,
            "state": "failed",
            "detail": "Workflow Web bloqué : deux autorisations exactes sont obligatoires.",
        }
    result = browser_workflow.execute_steps(
        raw_url=request.url,
        steps=request.steps,
        verify_text=request.verify_text,
        session_name=request.session_name,
    )
    audit_log.record(
        "browser_workflow",
        action="browser.execute_multistep",
        ok=bool(result.get("ok")),
        metadata={
            "state": result.get("state"),
            "steps": len(request.steps),
            "verified": result.get("verified"),
        },
    )
    return result
