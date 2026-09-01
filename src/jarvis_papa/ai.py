import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from jarvis_papa.config import settings


class AIUnavailable(RuntimeError):
    """Raised when the configured local AI provider cannot answer."""


@dataclass(frozen=True, slots=True)
class AIResponse:
    content: str
    tool_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class DraftReply:
    body: str
    generated_by_ai: bool


class OllamaAI:
    """Small local-first Ollama client using only the Python standard library."""

    @property
    def enabled(self) -> bool:
        return settings.ai_enabled and settings.ai_provider.lower() == "ollama"

    def status(self) -> dict[str, object]:
        if not self.enabled:
            return {"enabled": False, "available": False, "provider": settings.ai_provider}
        try:
            request = urllib.request.Request(
                f"{settings.ollama_url.rstrip('/')}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return {
                "enabled": True,
                "available": False,
                "provider": "ollama",
                "model": settings.ollama_model,
            }

        models = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
        return {
            "enabled": True,
            "available": True,
            "provider": "ollama",
            "model": settings.ollama_model,
            "model_installed": settings.ollama_model in models,
        }

    def ready(self) -> bool:
        state = self.status()
        return bool(state.get("available")) and state.get("model_installed") is not False

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        format_schema: dict[str, Any] | None = None,
    ) -> AIResponse:
        if not self.enabled:
            raise AIUnavailable("Le moteur IA local est désactivé.")

        payload: dict[str, Any] = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": settings.ai_temperature},
        }
        if tools:
            payload["tools"] = tools
        if format_schema:
            payload["format"] = format_schema

        request = urllib.request.Request(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.ai_timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise AIUnavailable("Ollama ne répond pas.") from exc

        message = raw.get("message")
        if not isinstance(message, dict):
            raise AIUnavailable("Réponse Ollama invalide.")
        content = str(message.get("content") or "").strip()
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            tool_calls = []
        return AIResponse(content=content, tool_calls=tuple(item for item in tool_calls if isinstance(item, dict)))

    def draft_reply(
        self,
        *,
        author: str,
        subject: str,
        body: str,
        attachment_names: tuple[str, ...] = (),
        memory_context: str = "",
    ) -> DraftReply:
        fallback = (
            "Bonjour,\n\nMerci pour votre message. J’ai bien reçu votre demande."
            + (" Vous trouverez le document demandé en pièce jointe." if attachment_names else "")
            + "\n\nCordialement,\nRobert"
        )
        if not self.enabled or not self.ready():
            return DraftReply(fallback, False)

        schema = {
            "type": "object",
            "properties": {"body": {"type": "string"}},
            "required": ["body"],
            "additionalProperties": False,
        }
        prompt = (
            "Rédige une réponse e-mail courte, naturelle et polie en français au nom de Robert. "
            "N'invente aucun fait, montant, date, engagement ou pièce jointe. "
            "Si une pièce jointe est fournie, indique seulement qu'elle est jointe.\n\n"
            f"Expéditeur: {author}\nObjet: {subject}\nMessage: {body[:6000]}\n"
            f"Pièces jointes prévues: {', '.join(attachment_names) or 'aucune'}\n"
            f"Contexte mémoire utile: {memory_context or 'aucun'}"
        )
        try:
            response = self.chat(
                [
                    {"role": "system", "content": "Tu es Jarvis, assistant personnel prudent de Robert."},
                    {"role": "user", "content": prompt},
                ],
                format_schema=schema,
            )
            parsed = json.loads(response.content)
            generated = str(parsed.get("body") or "").strip()
            if generated:
                return DraftReply(generated, True)
        except (AIUnavailable, json.JSONDecodeError, AttributeError):
            pass
        return DraftReply(fallback, False)


local_ai = OllamaAI()
