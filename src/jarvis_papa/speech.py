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
    sensitive: bool = False
    privacy_fallback_text: str | None = None


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
    """Generate natural French speech while respecting local privacy rules."""

    @property
    def available(self) -> bool:
        status = voice_service.status()
        providers = status.get("providers", {})
        return any(
            isinstance(item, dict) and bool(item.get("available"))
            for item in providers.values()
        ) if isinstance(providers, dict) else False

    def speak_async(self, event: SpeechEvent) -> bool:
        priority = event.importance.value
        if event.user_initiated and priority == SpeechImportance.NORMAL.value:
            priority = SpeechImportance.HIGH.value
        result = voice_service.speak(
            event.text,
            sensitive=event.sensitive,
            priority=priority,
        )
        if result.ok:
            return True
        # If sensitive local TTS is unavailable, do not leak the mail text to a cloud voice.
        # A generic, non-sensitive notification may still use the premium provider chain.
        if event.sensitive and event.privacy_fallback_text:
            return voice_service.speak(
                event.privacy_fallback_text,
                sensitive=False,
                priority=priority,
            ).ok
        return False


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
            spoken = self.speaker.speak_async(event)
            if event.dedupe_key and spoken:
                self._remember(event.dedupe_key)
        return decision, spoken

    def stop(self) -> bool:
        return voice_service.stop(clear_queue=True)

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
