import time
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock

from jarvis_papa.config import settings
from jarvis_papa.voice import voice_service


class SpeechImportance(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SpeechEvent:
    text: str
    importance: SpeechImportance = SpeechImportance.NORMAL
    user_initiated: bool = False
    action_required: bool = False
    dedupe_key: str | None = None


@dataclass(frozen=True)
class SpeechDecision:
    should_speak: bool
    reason: str


class SpeechPolicy:
    """Decide whether an event deserves to interrupt Robert with spoken audio."""

    def evaluate(self, event: SpeechEvent, *, duplicate: bool = False) -> SpeechDecision:
        if not settings.speech_enabled:
            return SpeechDecision(False, "speech_disabled")
        if not event.text.strip():
            return SpeechDecision(False, "empty_text")
        if duplicate and not event.user_initiated:
            return SpeechDecision(False, "recent_duplicate")
        if event.user_initiated:
            return SpeechDecision(True, "direct_response_to_robert")
        if event.importance is SpeechImportance.CRITICAL:
            return SpeechDecision(True, "critical_information")
        if event.action_required:
            return SpeechDecision(True, "robert_action_required")
        if event.importance is SpeechImportance.HIGH:
            return SpeechDecision(True, "important_information")
        return SpeechDecision(False, "not_important_enough_to_interrupt")


class SmartSpeaker:
    """Generate a natural French voice, with automatic provider fallback."""

    @property
    def available(self) -> bool:
        status = voice_service.status()
        providers = status.get("providers", {})
        return any(bool(item.get("available")) for item in providers.values())

    def speak_async(self, text: str) -> bool:
        return voice_service.speak(text).ok


class SpeechCoordinator:
    def __init__(self) -> None:
        self.policy = SpeechPolicy()
        self.speaker = SmartSpeaker()
        self._recent: dict[str, float] = {}
        self._lock = Lock()

    def handle(self, event: SpeechEvent) -> tuple[SpeechDecision, bool]:
        duplicate = self._is_recent_duplicate(event.dedupe_key)
        decision = self.policy.evaluate(event, duplicate=duplicate)
        spoken = False
        if decision.should_speak:
            spoken = self.speaker.speak_async(event.text)
            if event.dedupe_key and spoken:
                self._remember(event.dedupe_key)
        return decision, spoken

    def _is_recent_duplicate(self, key: str | None) -> bool:
        if not key:
            return False
        now = time.monotonic()
        with self._lock:
            seen_at = self._recent.get(key)
            if seen_at is None:
                return False
            return now - seen_at < settings.speech_repeat_cooldown_seconds

    def _remember(self, key: str) -> None:
        with self._lock:
            self._recent[key] = time.monotonic()


speech_coordinator = SpeechCoordinator()
