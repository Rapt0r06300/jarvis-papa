import json
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from jarvis_papa.actions import action_queue
from jarvis_papa.ai import AIUnavailable, local_ai
from jarvis_papa.browser import browser_agent
from jarvis_papa.desktop import desktop_controller
from jarvis_papa.files import file_searcher
from jarvis_papa.memory import memory_store
from jarvis_papa.windows_automation import windows_uia


@dataclass(frozen=True, slots=True)
class AgentResult:
    ok: bool
    answer: str
    tools_used: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class JarvisAgent:
    """Read-oriented agent loop. Sensitive actions stay outside LLM tool access."""

    TOOLS: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "function",
            "function": {
                "name": "pending_actions",
                "description": "Voir les éléments importants qui attendent Robert dans Jarvis.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "Chercher des fichiers locaux utiles pour Robert.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "open_app",
                "description": "Ouvrir une application autorisée comme Thunderbird ou l'Explorateur.",
                "parameters": {
                    "type": "object",
                    "properties": {"app": {"type": "string"}},
                    "required": ["app"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_read",
                "description": "Lire une page web publique avec Playwright.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_recall",
                "description": "Retrouver une préférence ou information mémorisée localement.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_list",
                "description": "Lister les fenêtres Windows ouvertes, sans rien modifier.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "windows_inspect",
                "description": "Inspecter les boutons et champs d'une fenêtre Windows sans cliquer.",
                "parameters": {
                    "type": "object",
                    "properties": {"window_title": {"type": "string"}},
                    "required": ["window_title"],
                },
            },
        },
    ]

    def run(self, prompt: str) -> AgentResult:
        if not local_ai.ready():
            return AgentResult(False, "Le moteur IA local Ollama n'est pas disponible.")

        memory_context = memory_store.context_for(prompt)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Tu es Jarvis, assistant personnel prudent de Robert. "
                    "Utilise les outils seulement si nécessaire. Tu n'as accès qu'à des outils de lecture "
                    "ou d'ouverture non destructive. N'invente jamais le résultat d'une action. "
                    "Pour un point de situation, consulte d'abord pending_actions. "
                    "Réponds en français, court et clair."
                ),
            },
            {
                "role": "user",
                "content": prompt + (f"\n\nMémoire locale utile:\n{memory_context}" if memory_context else ""),
            },
        ]
        try:
            response = local_ai.chat(messages, tools=self.TOOLS)
        except AIUnavailable:
            return AgentResult(False, "Le moteur IA local Ollama n'est pas disponible.")

        if not response.tool_calls:
            return AgentResult(True, response.content or "Je n'ai rien à ajouter.")

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
                "tool_calls": list(response.tool_calls),
            }
        )
        used: list[str] = []
        for call in response.tool_calls[:4]:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "")
            arguments = function.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            result = self._execute_tool(name, arguments)
            used.append(name)
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        try:
            final = local_ai.chat(messages)
        except AIUnavailable:
            return AgentResult(True, "J'ai exécuté les actions de lecture demandées.", tuple(used))
        return AgentResult(True, final.content or "Terminé.", tuple(used))

    @staticmethod
    def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, object]:
        if name == "pending_actions":
            return {
                "actions": [
                    {
                        "title": card.title,
                        "summary": card.summary,
                        "source": card.source,
                        "importance": card.importance,
                    }
                    for card in action_queue.list()[:10]
                ]
            }
        if name == "search_files":
            query = str(arguments.get("query") or "")
            return {
                "results": [item.to_dict() for item in file_searcher.search(query, limit=8)],
                "backend": file_searcher.backend,
            }
        if name == "open_app":
            return desktop_controller.start_app(str(arguments.get("app") or "")).to_dict()
        if name == "browser_read":
            return browser_agent.read_url(str(arguments.get("url") or "")).to_dict()
        if name == "memory_recall":
            items = memory_store.recall(str(arguments.get("query") or ""), limit=6)
            return {"results": [item.to_dict() for item in items]}
        if name == "windows_list":
            return windows_uia.list_windows().to_dict()
        if name == "windows_inspect":
            return windows_uia.inspect_window(str(arguments.get("window_title") or "")).to_dict()
        return {"ok": False, "error": "outil_non_autorise"}


jarvis_agent = JarvisAgent()
