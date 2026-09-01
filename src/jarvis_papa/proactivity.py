from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum

from jarvis_papa.actions import ActionCard, action_queue


class AttentionLevel(StrEnum):
    URGENT = "urgent"
    IMPORTANT = "important"
    NORMAL = "normal"
    SECONDARY = "secondary"


@dataclass(frozen=True, slots=True)
class ProactiveEvent:
    event_id: int
    kind: str
    level: AttentionLevel
    title: str
    detail: str
    source: str
    created_at: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["level"] = self.level.value
        return payload


class ProactiveEventBus:
    """Small in-memory event bus; no spam and no autonomous mutation."""

    MAX_EVENTS = 200

    def __init__(self) -> None:
        self._events: deque[ProactiveEvent] = deque(maxlen=self.MAX_EVENTS)
        self._counter = 0
        self._lock = threading.Lock()

    def publish(
        self,
        *,
        kind: str,
        level: AttentionLevel,
        title: str,
        detail: str,
        source: str = "jarvis",
    ) -> ProactiveEvent:
        with self._lock:
            self._counter += 1
            event = ProactiveEvent(
                event_id=self._counter,
                kind=kind[:100],
                level=level,
                title=" ".join(title.split()).strip()[:220],
                detail=" ".join(detail.split()).strip()[:700],
                source=source[:100],
                created_at=time.time(),
            )
            self._events.append(event)
            return event

    def after(self, event_id: int = 0) -> list[ProactiveEvent]:
        with self._lock:
            return [item for item in self._events if item.event_id > event_id]


class BriefingService:
    """Returns at most three genuinely useful things, with calm prioritization."""

    @staticmethod
    def priority(card: ActionCard) -> AttentionLevel:
        category = str(card.metadata.get("category") or "").casefold()
        source = f"{card.source} {card.title}".casefold()
        if card.priority_score >= 90 or card.importance == "critical":
            return AttentionLevel.URGENT
        if card.priority_score >= 60 or category in {"important", "suspicious"}:
            return AttentionLevel.IMPORTANT
        if category == "newsletter" or any(term in source for term in ("newsletter", "promotion", "publicité")):
            return AttentionLevel.SECONDARY
        return AttentionLevel.NORMAL

    def current(self, limit: int = 3) -> dict[str, object]:
        visible = []
        secondary = 0
        for card in action_queue.list():
            level = self.priority(card)
            if level is AttentionLevel.SECONDARY:
                secondary += 1
                continue
            visible.append((self._rank(level), card.priority_score, card, level))
        visible.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = visible[: max(1, min(int(limit), 3))]
        items = [
            {
                "ordinal": index,
                "card_id": card.id,
                "title": card.title,
                "summary": card.summary,
                "source": card.source,
                "level": level.value,
                "deadline": card.metadata.get("deadline_text"),
                "recommended_action": card.metadata.get("recommended_action"),
            }
            for index, (_, _, card, level) in enumerate(selected, start=1)
        ]
        return {
            "ok": True,
            "items": items,
            "secondary_count": secondary,
            "detail": self._human(items, secondary),
        }

    @staticmethod
    def _rank(level: AttentionLevel) -> int:
        return {
            AttentionLevel.URGENT: 4,
            AttentionLevel.IMPORTANT: 3,
            AttentionLevel.NORMAL: 2,
            AttentionLevel.SECONDARY: 1,
        }[level]

    @staticmethod
    def _human(items: list[dict[str, object]], secondary: int) -> str:
        if not items:
            return "Rien d'important ne demande ton attention pour le moment."
        if len(items) == 1:
            first = items[0]
            return f"Tu as une chose importante : {first['title']}. Le reste peut attendre."
        lines = [f"{index}. {item['title']}" for index, item in enumerate(items, start=1)]
        tail = f" {secondary} élément(s) secondaire(s) peuvent attendre." if secondary else ""
        return f"Tu as {len(items)} choses à regarder. " + " ".join(lines) + tail


proactive_events = ProactiveEventBus()
briefing_service = BriefingService()
