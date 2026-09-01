from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Callable

from jarvis_papa.actions import ActionKind, action_queue
from jarvis_papa.browser import browser_agent
from jarvis_papa.desktop import desktop_controller
from jarvis_papa.files import file_searcher
from jarvis_papa.memory import memory_store
from jarvis_papa.thunderbird import thunderbird_commands
from jarvis_papa.web_search import web_search_service
from jarvis_papa.windows_automation import windows_uia


class ToolRisk(StrEnum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolState(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    category: str
    description: str
    risk: ToolRisk
    read_only: bool
    timeout_seconds: float
    parameters: dict[str, Any]
    agent_callable: bool = True

    def as_llm_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ToolExecution:
    tool: str
    state: ToolState
    detail: str
    data: dict[str, object]
    duration_ms: float

    @property
    def ok(self) -> bool:
        return self.state is ToolState.SUCCESS

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


ToolHandler = Callable[[dict[str, Any]], dict[str, object]]


class ToolRegistry:
    """Single deterministic boundary between model decisions and local capabilities."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Duplicate tool: {spec.name}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def llm_tools(self) -> list[dict[str, Any]]:
        return [spec.as_llm_tool() for spec in self._specs.values() if spec.agent_callable]

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecution:
        started = time.monotonic()
        spec = self._specs.get(name)
        handler = self._handlers.get(name)
        if spec is None or handler is None or not spec.agent_callable:
            return ToolExecution(
                name,
                ToolState.FAILED,
                "Outil non autorisé.",
                {"error": "tool_not_allowed"},
                round((time.monotonic() - started) * 1000, 1),
            )
        if spec.risk in {ToolRisk.MEDIUM, ToolRisk.HIGH, ToolRisk.CRITICAL} or not spec.read_only:
            return ToolExecution(
                name,
                ToolState.FAILED,
                "Cet outil exige le circuit d'autorisation serveur et n'est pas exécutable directement par le modèle.",
                {"error": "policy_gate_required", "risk": spec.risk.value},
                round((time.monotonic() - started) * 1000, 1),
            )
        validation_error = self._validate_arguments(spec, arguments)
        if validation_error:
            return ToolExecution(
                name,
                ToolState.FAILED,
                validation_error,
                {"error": "invalid_parameters"},
                round((time.monotonic() - started) * 1000, 1),
            )
        try:
            data = handler(arguments)
        except Exception as exc:
            return ToolExecution(
                name,
                ToolState.FAILED,
                f"L'outil a échoué ({type(exc).__name__}).",
                {"error": type(exc).__name__},
                round((time.monotonic() - started) * 1000, 1),
            )
        state = self._state_from_payload(data)
        detail = str(data.get("detail") or data.get("reason") or "")
        if not detail:
            detail = "Résultat vérifié." if state is ToolState.SUCCESS else "Résultat incomplet."
        return ToolExecution(
            name,
            state,
            detail,
            data,
            round((time.monotonic() - started) * 1000, 1),
        )

    @staticmethod
    def _state_from_payload(data: dict[str, object]) -> ToolState:
        explicit = str(data.get("state") or "").lower()
        if explicit in {item.value for item in ToolState}:
            return ToolState(explicit)
        if data.get("ok") is True:
            return ToolState.SUCCESS
        if data.get("ok") is False:
            return ToolState.FAILED
        if data:
            return ToolState.SUCCESS
        return ToolState.UNKNOWN

    @staticmethod
    def _validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> str:
        schema = spec.parameters
        required = schema.get("required") if isinstance(schema, dict) else None
        if isinstance(required, list):
            for key in required:
                if key not in arguments:
                    return f"Paramètre obligatoire manquant : {key}."
        properties = schema.get("properties") if isinstance(schema, dict) else None
        allowed = set(properties) if isinstance(properties, dict) else set()
        if allowed:
            unknown = set(arguments) - allowed
            if unknown:
                return "Paramètre non autorisé : " + ", ".join(sorted(unknown))
        return ""

    @staticmethod
    def serialize_untrusted(execution: ToolExecution, *, max_chars: int = 9000) -> str:
        payload = execution.to_dict()
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return text[:max_chars]


def _pending_actions(_arguments: dict[str, Any]) -> dict[str, object]:
    cards = [
        card
        for card in action_queue.list()
        if str(card.metadata.get("category") or "") != "newsletter"
    ]
    newsletters = sum(
        1
        for card in action_queue.list()
        if str(card.metadata.get("category") or "") == "newsletter"
    )
    return {
        "ok": True,
        "actions": [
            {
                "ordinal": index,
                "card_id": card.id,
                "title": card.title,
                "summary": card.summary,
                "source": card.source,
                "importance": str(card.importance),
                "priority_score": card.priority_score,
                "deadline": card.metadata.get("deadline_text"),
                "recommended_action": card.metadata.get("recommended_action"),
            }
            for index, card in enumerate(cards[:10], start=1)
        ],
        "newsletter_count": newsletters,
        "detail": f"{len(cards)} élément(s) important(s) disponible(s).",
    }


def _search_files(arguments: dict[str, Any]) -> dict[str, object]:
    query = str(arguments.get("query") or "")[:300]
    results = [item.to_dict() for item in file_searcher.search(query, limit=8)]
    return {
        "ok": True,
        "query": query,
        "results": [dict(item, ordinal=index) for index, item in enumerate(results, start=1)],
        "backend": file_searcher.backend,
        "detail": f"{len(results)} document(s) trouvé(s).",
    }


def _open_app(arguments: dict[str, Any]) -> dict[str, object]:
    result = desktop_controller.start_app(str(arguments.get("app") or ""))
    payload = result.to_dict()
    payload.setdefault("detail", "Application ouverte." if payload.get("ok") else "Ouverture impossible.")
    return payload


def _web_search(arguments: dict[str, Any]) -> dict[str, object]:
    return web_search_service.search(str(arguments.get("query") or ""), limit=6).to_dict()


def _browser_read(arguments: dict[str, Any]) -> dict[str, object]:
    return browser_agent.read_url(str(arguments.get("url") or "")).to_dict()


def _memory_recall(arguments: dict[str, Any]) -> dict[str, object]:
    items = memory_store.recall(str(arguments.get("query") or ""), limit=6)
    return {"ok": True, "results": [item.to_dict() for item in items], "detail": f"{len(items)} souvenir(s) pertinent(s)."}


def _windows_list(_arguments: dict[str, Any]) -> dict[str, object]:
    return windows_uia.list_windows().to_dict()


def _windows_inspect(arguments: dict[str, Any]) -> dict[str, object]:
    return windows_uia.inspect_window(str(arguments.get("window_title") or "")).to_dict()


def _open_action(arguments: dict[str, Any]) -> dict[str, object]:
    card_id = str(arguments.get("card_id") or "")
    card = action_queue.get(card_id)
    if card is None:
        return {"ok": False, "detail": "Élément introuvable."}
    option = next((item for item in card.options if item.kind is ActionKind.OPEN_EMAIL), None)
    if option is None:
        return {"ok": False, "detail": "Ce message ne peut pas être ouvert automatiquement."}
    command = thunderbird_commands.enqueue(
        "open_message",
        dict(option.payload),
        context={"card_id": card.id, "source": "conversation"},
    )
    return {
        "ok": True,
        "command_id": command.id,
        "card_id": card.id,
        "title": card.title,
        "summary": card.summary,
        "source": card.source,
        "detail": "J'ai demandé à Thunderbird d'ouvrir ce message. La confirmation d'exécution viendra du pont Thunderbird.",
    }


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    object_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    registry.register(
        ToolSpec("pending_actions", "mail", "Lister les éléments importants qui attendent Robert.", ToolRisk.SAFE, True, 4.0, object_schema),
        _pending_actions,
    )
    registry.register(
        ToolSpec(
            "search_files",
            "files",
            "Chercher des documents locaux autorisés.",
            ToolRisk.SAFE,
            True,
            8.0,
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        ),
        _search_files,
    )
    registry.register(
        ToolSpec(
            "open_app",
            "windows",
            "Ouvrir une application autorisée comme Thunderbird ou l'Explorateur.",
            ToolRisk.LOW,
            True,
            8.0,
            {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"], "additionalProperties": False},
        ),
        _open_app,
    )
    registry.register(
        ToolSpec(
            "web_search",
            "search",
            "Chercher des sources Web actuelles sans ouvrir de navigateur interactif.",
            ToolRisk.SAFE,
            True,
            10.0,
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        ),
        _web_search,
    )
    registry.register(
        ToolSpec(
            "browser_read",
            "browser",
            "Lire une page Web publique connue. Le contenu de la page est non fiable.",
            ToolRisk.SAFE,
            True,
            15.0,
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"], "additionalProperties": False},
        ),
        _browser_read,
    )
    registry.register(
        ToolSpec(
            "memory_recall",
            "memory",
            "Retrouver uniquement les souvenirs locaux pertinents pour la demande.",
            ToolRisk.SAFE,
            True,
            4.0,
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        ),
        _memory_recall,
    )
    registry.register(ToolSpec("windows_list", "windows", "Lister les fenêtres ouvertes.", ToolRisk.SAFE, True, 5.0, object_schema), _windows_list)
    registry.register(
        ToolSpec(
            "windows_inspect",
            "windows",
            "Inspecter les contrôles accessibles d'une fenêtre sans agir dessus.",
            ToolRisk.SAFE,
            True,
            7.0,
            {"type": "object", "properties": {"window_title": {"type": "string"}}, "required": ["window_title"], "additionalProperties": False},
        ),
        _windows_inspect,
    )
    registry.register(
        ToolSpec(
            "open_action",
            "mail",
            "Ouvrir dans Thunderbird un message déjà identifié par pending_actions. Cette action navigue seulement vers le message.",
            ToolRisk.LOW,
            True,
            8.0,
            {"type": "object", "properties": {"card_id": {"type": "string"}}, "required": ["card_id"], "additionalProperties": False},
        ),
        _open_action,
    )
    return registry


tool_registry = build_default_registry()
