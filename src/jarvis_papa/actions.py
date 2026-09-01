from dataclasses import asdict, dataclass, field
from enum import StrEnum
from threading import Lock
from uuid import uuid4


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ActionQueue:
    def __init__(self, max_items: int = 50) -> None:
        self.max_items = max_items
        self._cards: list[ActionCard] = []
        self._lock = Lock()

    def add(self, card: ActionCard) -> ActionCard:
        with self._lock:
            self._cards = [item for item in self._cards if item.id != card.id]
            self._cards.insert(0, card)
            del self._cards[self.max_items :]
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
        )
        return self.add(card)

    def list(self) -> list[ActionCard]:
        with self._lock:
            return list(self._cards)

    def get(self, card_id: str) -> ActionCard | None:
        with self._lock:
            return next((card for card in self._cards if card.id == card_id), None)

    def remove(self, card_id: str) -> bool:
        with self._lock:
            before = len(self._cards)
            self._cards = [card for card in self._cards if card.id != card_id]
            return len(self._cards) != before


action_queue = ActionQueue()
