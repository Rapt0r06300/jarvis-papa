from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from uuid import uuid4

from jarvis_papa.agent import IntentRouter, jarvis_agent


@dataclass(slots=True)
class ConversationSession:
    id: str
    created_at: float
    updated_at: float
    messages: list[dict[str, str]] = field(default_factory=list)
    observations: list[dict[str, object]] = field(default_factory=list)
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
    """Bounded session context for natural follow-up references such as 'the second one'."""

    MAX_SESSIONS = 32
    SESSION_TTL_SECONDS = 8 * 3600
    MAX_MESSAGES = 14
    MAX_OBSERVATIONS = 8

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.Lock()

    def turn(self, text: str, *, conversation_id: str | None = None) -> ConversationTurn:
        started = time.monotonic()
        request_id = uuid4().hex
        session = self._get_or_create(conversation_id)
        route = IntentRouter.route(text)

        def is_cancelled() -> bool:
            with self._lock:
                current = self._sessions.get(session.id)
                return bool(current and request_id in current.cancelled_request_ids)

        with self._lock:
            history = list(session.messages[-self.MAX_MESSAGES :])
            context = list(session.observations[-self.MAX_OBSERVATIONS :])

        result = jarvis_agent.run(
            text,
            history=history,
            conversation_context=context,
            route=route,
            is_cancelled=is_cancelled,
        )

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
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                return False
            session.cancelled_request_ids.add(request_id)
            session.updated_at = time.time()
            return True

    def reset(self, conversation_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(conversation_id, None) is not None

    def snapshot(self, conversation_id: str) -> dict[str, object] | None:
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                return None
            return {
                "conversation_id": session.id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "messages": list(session.messages),
            }

    def _get_or_create(self, conversation_id: str | None) -> ConversationSession:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            if conversation_id:
                existing = self._sessions.get(conversation_id)
                if existing is not None:
                    existing.updated_at = now
                    return existing
            session = ConversationSession(uuid4().hex, now, now)
            self._sessions[session.id] = session
            if len(self._sessions) > self.MAX_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda item: item.updated_at)
                if oldest.id != session.id:
                    self._sessions.pop(oldest.id, None)
            return session

    def _cleanup_locked(self, now: float) -> None:
        expired = [
            key
            for key, session in self._sessions.items()
            if now - session.updated_at > self.SESSION_TTL_SECONDS
        ]
        for key in expired:
            self._sessions.pop(key, None)


conversation_manager = ConversationManager()
