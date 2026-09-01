from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from jarvis_papa import __version__
from jarvis_papa.config import settings
from jarvis_papa.security import ActionRisk, security_policy
from jarvis_papa.speech import SpeechEvent, SpeechImportance, speech_coordinator


class SecurityCheckRequest(BaseModel):
    risk: ActionRisk
    confirmed: bool = False


class SpeechEventRequest(BaseModel):
    text: str
    importance: SpeechImportance = SpeechImportance.NORMAL
    user_initiated: bool = False
    action_required: bool = False
    dedupe_key: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="API locale de Jarvis Papa",
    )

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return f"""
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Papa</title>
  <style>
    :root {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; color-scheme: dark; }}
    body {{ margin: 0; background: #0b1020; color: #f5f7ff; min-height: 100vh; display: grid; place-items: center; }}
    main {{ width: min(760px, calc(100% - 32px)); }}
    .card {{ background: #141b31; border: 1px solid #293352; border-radius: 22px; padding: 28px; box-shadow: 0 18px 60px #0006; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(34px, 6vw, 58px); }}
    p {{ color: #b9c2df; line-height: 1.6; }}
    .status {{ display: inline-flex; gap: 9px; align-items: center; padding: 9px 13px; border-radius: 999px; background: #172a23; color: #aef0c8; font-weight: 700; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #62db91; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 24px; }}
    .module {{ padding: 16px; border-radius: 16px; background: #0f1528; border: 1px solid #242e4b; }}
    .module strong {{ display: block; margin-bottom: 6px; }}
    .soon {{ color: #7f8aaa; font-size: 14px; }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <div class="status"><span class="dot"></span> Jarvis est prêt</div>
      <h1>Bonjour {settings.user_name} 👋</h1>
      <p>Jarvis fonctionne sans microphone. {settings.user_name} interagit par clics et clavier, et Jarvis décide lui-même quand une réponse mérite d'être dite à voix haute.</p>
      <div class="grid">
        <div class="module"><strong>📧 Mails</strong><span class="soon">À connecter</span></div>
        <div class="module"><strong>📁 Fichiers</strong><span class="soon">À connecter</span></div>
        <div class="module"><strong>🔊 Voix intelligente</strong><span class="soon">Active côté moteur</span></div>
        <div class="module"><strong>📅 Agenda</strong><span class="soon">À connecter</span></div>
      </div>
    </section>
  </main>
</body>
</html>
"""

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
            "modules": {
                "mail": "planned",
                "files": "planned",
                "voice_input": "disabled_no_microphone",
                "voice_output": "intelligent_policy_ready",
                "calendar": "planned",
            },
        }

    @app.post("/api/security/check")
    def security_check(request: SecurityCheckRequest) -> dict[str, object]:
        decision = security_policy.evaluate(request.risk, confirmed=request.confirmed)
        return {
            "risk": request.risk,
            "allowed": decision.allowed,
            "requires_confirmation": decision.requires_confirmation,
            "reason": decision.reason,
        }

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
        return {
            "should_speak": decision.should_speak,
            "spoken": spoken,
            "reason": decision.reason,
        }

    return app


app = create_app()
