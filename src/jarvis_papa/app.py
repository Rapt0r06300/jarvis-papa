from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from jarvis_papa import __version__
from jarvis_papa.actions import ActionKind, action_queue
from jarvis_papa.config import settings
from jarvis_papa.desktop import desktop_controller
from jarvis_papa.files import file_searcher
from jarvis_papa.mail import IncomingMail, mail_assistant
from jarvis_papa.security import ActionRisk, security_policy
from jarvis_papa.speech import SpeechEvent, SpeechImportance, speech_coordinator
from jarvis_papa.thunderbird import thunderbird_commands


class SecurityCheckRequest(BaseModel):
    risk: ActionRisk
    confirmed: bool = False


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


class ActionExecuteRequest(BaseModel):
    option_id: str
    confirmed: bool = False


class OpenPathRequest(BaseModel):
    path: str


class StartAppRequest(BaseModel):
    app: str


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="API locale de Jarvis Papa",
    )

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard_html()

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
                "mail": "bridge_ready",
                "files": file_searcher.backend,
                "desktop": "windows_safe_actions_ready",
                "voice_input": "disabled_no_microphone",
                "voice_output": "intelligent_policy_ready",
                "browser": "basic_search_ready",
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
        speech_reason = "not_important_enough_to_interrupt"
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
            "noise": assessment.is_noise,
            "importance": assessment.importance.value,
            "action_required": assessment.action_required,
            "card": card.to_dict() if card else None,
            "speech": {"spoken": spoken, "reason": speech_reason},
        }

    @app.get("/api/actions")
    def list_actions() -> list[dict[str, object]]:
        return [card.to_dict() for card in action_queue.list()]

    @app.post("/api/actions/{card_id}/execute")
    def execute_action(card_id: str, request: ActionExecuteRequest) -> dict[str, object]:
        card = action_queue.get(card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Action introuvable.")

        option = next((item for item in card.options if item.id == request.option_id), None)
        if option is None:
            raise HTTPException(status_code=404, detail="Option introuvable.")

        if option.requires_confirmation:
            decision = security_policy.evaluate(ActionRisk.DESTRUCTIVE, confirmed=request.confirmed)
            if not decision.allowed:
                return {
                    "ok": False,
                    "requires_confirmation": True,
                    "reason": decision.reason,
                }

        if option.kind is ActionKind.SEARCH_FILES:
            query = str(option.payload.get("query", ""))
            results = [item.to_dict() for item in file_searcher.search(query)]
            return {"ok": True, "kind": option.kind, "results": results}

        if option.kind is ActionKind.OPEN_EMAIL:
            command = thunderbird_commands.enqueue("open_message", dict(option.payload))
            return {"ok": True, "kind": option.kind, "command_id": command.id}

        if option.kind is ActionKind.SEND_REPLY:
            payload = dict(option.payload)
            payload.setdefault(
                "body",
                "Bonjour,\n\nMerci pour votre message. J’ai bien reçu votre demande.\n\n"
                "Cordialement,\nRobert",
            )
            command = thunderbird_commands.enqueue("prepare_reply", payload)
            return {"ok": True, "kind": option.kind, "command_id": command.id}

        if option.kind is ActionKind.OPEN_FILE:
            path = str(option.payload.get("path", ""))
            return desktop_controller.open_path(path).to_dict()

        if option.kind is ActionKind.DISMISS:
            return {"ok": action_queue.remove(card_id), "kind": option.kind}

        raise HTTPException(status_code=400, detail="Action non gérée.")

    @app.delete("/api/actions/{card_id}")
    def dismiss_action(card_id: str) -> dict[str, bool]:
        return {"ok": action_queue.remove(card_id)}

    @app.get("/api/files/search")
    def search_files(
        q: str = Query(min_length=1, max_length=300),
        limit: int = Query(default=12, ge=1, le=30),
    ) -> dict[str, object]:
        results = file_searcher.search(q, limit=limit)
        return {
            "backend": file_searcher.backend,
            "results": [item.to_dict() for item in results],
        }

    @app.post("/api/files/open")
    def open_file(request: OpenPathRequest) -> dict[str, object]:
        decision = security_policy.evaluate(ActionRisk.READ)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        return desktop_controller.open_path(request.path).to_dict()

    @app.post("/api/desktop/start")
    def start_app(request: StartAppRequest) -> dict[str, object]:
        decision = security_policy.evaluate(ActionRisk.READ)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        return desktop_controller.start_app(request.app).to_dict()

    @app.post("/api/browser/search")
    def browser_search(request: WebSearchRequest) -> dict[str, object]:
        decision = security_policy.evaluate(ActionRisk.READ)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        return desktop_controller.search_web(request.query).to_dict()

    @app.get("/api/thunderbird/commands")
    def list_thunderbird_commands() -> list[dict[str, object]]:
        return [command.to_dict() for command in thunderbird_commands.pending()]

    @app.post("/api/thunderbird/commands/{command_id}/ack")
    def acknowledge_thunderbird_command(command_id: str) -> dict[str, bool]:
        return {"ok": thunderbird_commands.acknowledge(command_id)}

    return app


def _dashboard_html() -> str:
    return f"""
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Papa</title>
  <style>
    :root {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #0b1020; color: #f5f7ff; min-height: 100vh; }}
    main {{ width: min(920px, calc(100% - 28px)); margin: 32px auto 70px; }}
    .status {{ display: inline-flex; gap: 9px; align-items: center; padding: 9px 13px; border-radius: 999px; background: #172a23; color: #aef0c8; font-weight: 700; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #62db91; }}
    h1 {{ margin: 14px 0 4px; font-size: clamp(38px, 7vw, 66px); }}
    h2 {{ margin-top: 34px; }}
    p {{ color: #b9c2df; line-height: 1.55; }}
    .quick {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-top: 22px; }}
    button {{ border: 0; border-radius: 15px; padding: 15px 18px; font: inherit; font-weight: 750; cursor: pointer; background: #e9eeff; color: #10162a; }}
    button.secondary {{ background: #1c2745; color: #edf1ff; border: 1px solid #344164; }}
    .cards {{ display: grid; gap: 14px; }}
    .card {{ background: #141b31; border: 1px solid #293352; border-radius: 20px; padding: 20px; box-shadow: 0 14px 40px #0004; }}
    .card.high, .card.critical {{ border-color: #876735; }}
    .meta {{ color: #91a0ca; font-size: 14px; }}
    .summary {{ color: #d8def1; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 15px; }}
    .empty {{ padding: 22px; border: 1px dashed #344164; border-radius: 18px; color: #91a0ca; }}
    .files {{ margin-top: 14px; display: grid; gap: 8px; }}
    .file {{ padding: 11px; background: #0f1528; border-radius: 12px; display: flex; gap: 10px; justify-content: space-between; align-items: center; }}
    .file span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  </style>
</head>
<body>
<main>
  <div class="status"><span class="dot"></span> Jarvis est prêt</div>
  <h1>Bonjour {settings.user_name}</h1>
  <p>Jarvis surveille ce qui mérite ton attention et te propose seulement les actions utiles.</p>

  <div class="quick">
    <button onclick="startApp('thunderbird')">Ouvrir Thunderbird</button>
    <button class="secondary" onclick="startApp('explorer')">Ouvrir mes fichiers</button>
  </div>

  <h2>Ce qui demande ton attention</h2>
  <div id="cards" class="cards"><div class="empty">Chargement…</div></div>
</main>
<script>
const cardsEl = document.getElementById('cards');

async function api(path, options={{}}) {{
  const response = await fetch(path, {{
    headers: {{'Content-Type': 'application/json'}},
    ...options
  }});
  return response.json();
}}

async function startApp(app) {{
  await api('/api/desktop/start', {{method: 'POST', body: JSON.stringify({{app}})}});
}}

function button(label, onClick, secondary=false) {{
  const el = document.createElement('button');
  el.textContent = label;
  if (secondary) el.classList.add('secondary');
  el.onclick = onClick;
  return el;
}}

function renderFiles(container, files) {{
  const area = document.createElement('div');
  area.className = 'files';
  if (!files.length) {{
    area.textContent = 'Aucun document trouvé pour le moment.';
  }}
  for (const file of files) {{
    const row = document.createElement('div');
    row.className = 'file';
    const name = document.createElement('span');
    name.textContent = file.name;
    row.appendChild(name);
    row.appendChild(button('Ouvrir', async () => {{
      await api('/api/files/open', {{method: 'POST', body: JSON.stringify({{path: file.path}})}});
    }}));
    area.appendChild(row);
  }}
  container.appendChild(area);
}}

async function execute(card, option, cardElement) {{
  const result = await api(`/api/actions/${{card.id}}/execute`, {{
    method: 'POST',
    body: JSON.stringify({{option_id: option.id, confirmed: false}})
  }});
  if (result.requires_confirmation) {{
    const confirmed = window.confirm('Cette action est sensible. Confirmer ?');
    if (!confirmed) return;
    await api(`/api/actions/${{card.id}}/execute`, {{
      method: 'POST',
      body: JSON.stringify({{option_id: option.id, confirmed: true}})
    }});
    return;
  }}
  if (result.results) renderFiles(cardElement, result.results);
}}

async function refresh() {{
  const cards = await api('/api/actions');
  cardsEl.replaceChildren();
  if (!cards.length) {{
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'Rien d’important pour le moment.';
    cardsEl.appendChild(empty);
    return;
  }}
  for (const card of cards) {{
    const el = document.createElement('section');
    el.className = `card ${{card.importance || ''}}`;

    const title = document.createElement('h3');
    title.textContent = card.title;
    el.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = card.source;
    el.appendChild(meta);

    const summary = document.createElement('p');
    summary.className = 'summary';
    summary.textContent = card.summary;
    el.appendChild(summary);

    const actions = document.createElement('div');
    actions.className = 'actions';
    for (const option of card.options) {{
      actions.appendChild(button(option.label, () => execute(card, option, el), option.id !== 'find-files'));
    }}
    actions.appendChild(button('Plus tard', async () => {{
      await api(`/api/actions/${{card.id}}`, {{method: 'DELETE'}});
      refresh();
    }}, true));
    el.appendChild(actions);
    cardsEl.appendChild(el);
  }}
}}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


app = create_app()
