import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Lock
from uuid import uuid4

from jarvis_papa.config import settings


class ActionKind(StrEnum):
    OPEN_EMAIL = "open_email"
    OPEN_FILE = "open_file"
    SEARCH_FILES = "search_files"
    SEND_REPLY = "send_reply"
    DISMISS = "dismiss"


@dataclass(slots=True)
class ActionOption:
    id: str
    label: str
    kind: ActionKind
    payload: dict[str, object] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass(slots=True)
class ActionCard:
    id: str
    title: str
    summary: str
    source: str
    importance: str
    speech_text: str | None = None
    options: list[ActionOption] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    priority_score: int = 0
    dedupe_key: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    snoozed_until: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ActionQueue:
    """Persistent local queue for the few things Robert genuinely needs to see."""

    def __init__(self, max_items: int = 100, path: Path | None = None) -> None:
        self.max_items = max_items
        self.path = path or (settings.runtime_dir / "actions.json")
        self._cards: list[ActionCard] = []
        self._lock = Lock()
        self._load()

    def add(self, card: ActionCard) -> ActionCard:
        now = time.time()
        with self._lock:
            if card.dedupe_key:
                existing = next(
                    (item for item in self._cards if item.dedupe_key == card.dedupe_key),
                    None,
                )
            else:
                existing = None
            if existing is not None:
                card.id = existing.id
                card.created_at = existing.created_at
                card.snoozed_until = existing.snoozed_until
            card.updated_at = now
            self._cards = [item for item in self._cards if item.id != card.id]
            self._cards.append(card)
            self._trim_locked()
            self._save_locked()
        return card

    def create(
        self,
        *,
        title: str,
        summary: str,
        source: str,
        importance: str,
        speech_text: str | None = None,
        options: list[ActionOption] | None = None,
        metadata: dict[str, object] | None = None,
        priority_score: int = 0,
        dedupe_key: str | None = None,
    ) -> ActionCard:
        card = ActionCard(
            id=uuid4().hex,
            title=title,
            summary=summary,
            source=source,
            importance=importance,
            speech_text=speech_text,
            options=options or [],
            metadata=metadata or {},
            priority_score=max(0, min(100, int(priority_score))),
            dedupe_key=dedupe_key,
        )
        return self.add(card)

    def list(self, *, include_snoozed: bool = False) -> list[ActionCard]:
        now = time.time()
        with self._lock:
            cards = list(self._cards)
        if not include_snoozed:
            cards = [
                card
                for card in cards
                if card.snoozed_until is None or card.snoozed_until <= now
            ]
        cards.sort(key=lambda card: (card.priority_score, card.updated_at), reverse=True)
        return cards

    def get(self, card_id: str) -> ActionCard | None:
        with self._lock:
            return next((card for card in self._cards if card.id == card_id), None)

    def snooze(self, card_id: str, seconds: int = 4 * 60 * 60) -> bool:
        with self._lock:
            card = next((item for item in self._cards if item.id == card_id), None)
            if card is None:
                return False
            card.snoozed_until = time.time() + max(300, min(seconds, 7 * 24 * 60 * 60))
            card.updated_at = time.time()
            self._save_locked()
            return True

    def unsnooze_due(self) -> int:
        now = time.time()
        changed = 0
        with self._lock:
            for card in self._cards:
                if card.snoozed_until is not None and card.snoozed_until <= now:
                    card.snoozed_until = None
                    card.updated_at = now
                    changed += 1
            if changed:
                self._save_locked()
        return changed

    def remove(self, card_id: str) -> bool:
        with self._lock:
            before = len(self._cards)
            self._cards = [card for card in self._cards if card.id != card_id]
            changed = len(self._cards) != before
            if changed:
                self._save_locked()
            return changed

    def remove_many(self, card_ids: list[str]) -> int:
        ids = set(card_ids)
        with self._lock:
            before = len(self._cards)
            self._cards = [card for card in self._cards if card.id not in ids]
            removed = before - len(self._cards)
            if removed:
                self._save_locked()
            return removed

    def _trim_locked(self) -> None:
        self._cards.sort(key=lambda card: (card.priority_score, card.updated_at), reverse=True)
        del self._cards[self.max_items :]

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        cards: list[ActionCard] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                options = [
                    ActionOption(
                        id=str(option["id"]),
                        label=str(option["label"]),
                        kind=ActionKind(str(option["kind"])),
                        payload=dict(option.get("payload") or {}),
                        requires_confirmation=bool(option.get("requires_confirmation", False)),
                    )
                    for option in item.get("options", [])
                    if isinstance(option, dict)
                ]
                cards.append(
                    ActionCard(
                        id=str(item["id"]),
                        title=str(item.get("title") or "Action"),
                        summary=str(item.get("summary") or ""),
                        source=str(item.get("source") or "Jarvis"),
                        importance=str(item.get("importance") or "normal"),
                        speech_text=item.get("speech_text") if isinstance(item.get("speech_text"), str) else None,
                        options=options,
                        metadata=dict(item.get("metadata") or {}),
                        priority_score=int(item.get("priority_score") or 0),
                        dedupe_key=item.get("dedupe_key") if isinstance(item.get("dedupe_key"), str) else None,
                        created_at=float(item.get("created_at") or time.time()),
                        updated_at=float(item.get("updated_at") or time.time()),
                        snoozed_until=(
                            float(item["snoozed_until"])
                            if item.get("snoozed_until") is not None
                            else None
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self._cards = cards[: self.max_items]

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = [card.to_dict() for card in self._cards]
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


action_queue = ActionQueue()
