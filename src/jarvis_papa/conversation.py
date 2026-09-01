from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from uuid import uuid4

from jarvis_papa.agent import IntentRouter, jarvis_agent


_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


@dataclass(slots=True)
class ConversationSession:
    id: str
    created_at: float
    updated_at: float
    messages: list[dict[str, str]] = field(default_factory=list)
    observations: list[dict[str, object]] = field(default_factory=list)
    active_request_ids: set[str] = field(default_factory=set)
    cancelled_request_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    request_id: str
    conversation_id: str
    answer: str
    route: str
    model: str
    tools: tuple[str, ...]
    duration_ms: float
    retry_count: int
    final_state: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ConversationManager:
    """Bounded session context for natural follow-up references such as 'le deuxième'."""

    MAX_SESSIONS = 32
    SESSION_TTL_SECONDS = 8 * 3600
    MAX_MESSAGES = 14
    MAX_OBSERVATIONS = 8

    _REFERENTIAL_MARKERS = (
        "le premier",
        "le deuxième",
        "le deuxieme",
        "le second",
        "le troisième",
        "le troisieme",
        "celui-ci",
        "celui là",
        "celui-la",
        "celui-là",
        "ouvre-le",
        "ouvre la",
        "ouvre le",
        "résume-le",
        "resume-le",
        "résume le",
        "resume le",
        "qu'est-ce qu'ils veulent",
        "qu’est-ce qu’ils veulent",
        "prépare une réponse",
        "prepare une reponse",
        "réponds-lui",
        "reponds-lui",
    )

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()

    def turn(
        self,
        text: str,
        *,
        conversation_id: str | None = None,
        request_id: str | None = None,
    ) -> ConversationTurn:
        started = time.monotonic()
        request_id = self._normalize_id(request_id)
        session = self._get_or_create(conversation_id)

        with self._lock:
            history = list(session.messages[-self.MAX_MESSAGES :])
            context = list(session.observations[-self.MAX_OBSERVATIONS :])
            session.active_request_ids.add(request_id)

        route = self._resolve_route(text, context)

        def is_cancelled() -> bool:
            with self._lock:
                current = self._sessions.get(session.id)
                return bool(current and request_id in current.cancelled_request_ids)

        try:
            result = jarvis_agent.run(
                text,
                history=history,
                conversation_context=context,
                route=route,
                is_cancelled=is_cancelled,
            )
        finally:
            with self._lock:
                current = self._sessions.get(session.id)
                if current is not None:
                    current.active_request_ids.discard(request_id)

        with self._lock:
            current = self._sessions.get(session.id)
            if current is not None:
                current.updated_at = time.time()
                current.messages.append({"role": "user", "content": text[:5000]})
                current.messages.append({"role": "assistant", "content": result.answer[:5000]})
                current.messages = current.messages[-self.MAX_MESSAGES :]
                current.observations.extend(dict(item) for item in result.observations)
                current.observations = current.observations[-self.MAX_OBSERVATIONS :]
                current.cancelled_request_ids.discard(request_id)

        return ConversationTurn(
            request_id=request_id,
            conversation_id=session.id,
            answer=result.answer,
            route=result.route,
            model=result.model,
            tools=result.tools_used,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
            retry_count=result.retry_count,
            final_state=result.final_state,
        )

    def cancel(self, conversation_id: str, request_id: str) -> bool:
        conversation_id = self._normalize_existing_id(conversation_id)
        request_id = self._normalize_existing_id(request_id)
        if not conversation_id or not request_id:
            return False
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None or request_id not in session.active_request_ids:
                return False
            session.cancelled_request_ids.add(request_id)
            session.updated_at = time.time()
            return True

    def reset(self, conversation_id: str) -> bool:
        conversation_id = self._normalize_existing_id(conversation_id)
        if not conversation_id:
            return False
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None or session.active_request_ids:
                return False
            return self._sessions.pop(conversation_id, None) is not None

    def snapshot(self, conversation_id: str) -> dict[str, object] | None:
        conversation_id = self._normalize_existing_id(conversation_id)
        if not conversation_id:
            return None
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                return None
            return {
                "conversation_id": session.id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "messages": list(session.messages),
                "busy": bool(session.active_request_ids),
            }

    def _get_or_create(self, conversation_id: str | None) -> ConversationSession:
        now = time.time()
        requested = self._normalize_existing_id(conversation_id)
        with self._lock:
            self._cleanup_locked(now)
            if requested:
                existing = self._sessions.get(requested)
                if existing is not None:
                    existing.updated_at = now
                    return existing
                session_id = requested
            else:
                session_id = uuid4().hex
            session = ConversationSession(session_id, now, now)
            self._sessions[session.id] = session
            if len(self._sessions) > self.MAX_SESSIONS:
                idle_sessions = [item for item in self._sessions.values() if not item.active_request_ids]
                if idle_sessions:
                    oldest = min(idle_sessions, key=lambda item: item.updated_at)
                    if oldest.id != session.id:
                        self._sessions.pop(oldest.id, None)
            return session

    @classmethod
    def _resolve_route(cls, text: str, context: list[dict[str, object]]) -> str:
        route = IntentRouter.route(text)
        lowered = text.casefold()
        referential = any(marker in lowered for marker in cls._REFERENTIAL_MARKERS)
        if not referential:
            return route
        for observation in reversed(context):
            tool = str(observation.get("tool") or "")
            if tool in {"pending_actions", "open_action"}:
                return "mail"
            if tool == "search_files":
                return "files"
            if tool in {"windows_list", "windows_inspect", "open_app"}:
                return "windows"
            if tool in {"web_search", "web_read", "browser_read"}:
                return "current_info"
        return route

    @staticmethod
    def _normalize_id(value: str | None) -> str:
        if isinstance(value, str):
            cleaned = value.strip()
            if _ID_PATTERN.fullmatch(cleaned):
                return cleaned
        return uuid4().hex

    @staticmethod
    def _normalize_existing_id(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned if _ID_PATTERN.fullmatch(cleaned) else None

    def _cleanup_locked(self, now: float) -> None:
        expired = [
            key
            for key, session in self._sessions.items()
            if not session.active_request_ids
            and now - session.updated_at > self.SESSION_TTL_SECONDS
        ]
        for key in expired:
            self._sessions.pop(key, None)


conversation_manager = ConversationManager()
