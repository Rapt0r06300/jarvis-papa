from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from jarvis_papa.runtime_progress import (
    ProgressImportance,
    RuntimeProgressEvent,
    TruthfulProgressNarrator,
)
from jarvis_papa.speech import SpeechEvent, SpeechImportance, speech_coordinator

_LOGGER = logging.getLogger(__name__)

_SILENT_CATEGORIES = frozenset(
    {
        "newsletter",
        "newsletters",
        "noise",
        "low_priority",
        "ignore_for_briefing",
    }
)

SpeechHandler = Callable[[SpeechEvent], object]


@dataclass(frozen=True, slots=True)
class PresentationResult:
    visual_text: str
    speech_attempted: bool
    spoken: bool
    preempt: bool
    deduplicated: bool
    presentation_ok: bool = True
    speech_error: str | None = None


def speech_importance_for(importance: ProgressImportance) -> SpeechImportance:
    if not isinstance(importance, ProgressImportance):
        raise TypeError("speech priority requires ProgressImportance")
    return {
        ProgressImportance.SILENT: SpeechImportance.LOW,
        ProgressImportance.NORMAL: SpeechImportance.NORMAL,
        ProgressImportance.IMPORTANT: SpeechImportance.HIGH,
        ProgressImportance.CRITICAL: SpeechImportance.CRITICAL,
    }[importance]


class RuntimePresentationCoordinator:
    """Translate truthful runtime events into visual updates and optional speech.

    The runtime event remains authoritative. Audio is an optional side effect: it may be
    suppressed, deduplicated, preempt lower-priority audio, or fail without changing the
    underlying run state or hiding the visual update.
    """

    def __init__(
        self,
        *,
        speech_handler: SpeechHandler | None = None,
        narrator: TruthfulProgressNarrator | None = None,
    ) -> None:
        self._speech_handler = speech_handler or speech_coordinator.handle
        self._narrator = narrator or TruthfulProgressNarrator()
        self._spoken_semantics: set[str] = set()
        self.background_run_interrupted = False

    def present(
        self,
        event: RuntimeProgressEvent,
        *,
        category: str = "",
    ) -> PresentationResult:
        if not isinstance(event, RuntimeProgressEvent):
            raise TypeError("runtime presentation accepts RuntimeProgressEvent only")

        visual_text = self._narrator.narrate(event)
        normalized_category = _normalize_category(category)
        if self._is_silent(event, normalized_category):
            return PresentationResult(
                visual_text=visual_text,
                speech_attempted=False,
                spoken=False,
                preempt=False,
                deduplicated=False,
            )

        semantic_key = _semantic_key(event, normalized_category, visual_text)
        if semantic_key in self._spoken_semantics:
            return PresentationResult(
                visual_text=visual_text,
                speech_attempted=False,
                spoken=False,
                preempt=False,
                deduplicated=True,
            )

        effective_importance = event.importance
        has_priority_evidence = bool(event.evidence)
        preempt = effective_importance is ProgressImportance.CRITICAL and has_priority_evidence
        if effective_importance is ProgressImportance.CRITICAL and not has_priority_evidence:
            # Critical presentation is intentionally evidence-gated. Unsupported urgency can
            # still be visible and important, but it must not interrupt existing speech.
            effective_importance = ProgressImportance.IMPORTANT

        speech_event = SpeechEvent(
            text=visual_text,
            importance=speech_importance_for(effective_importance),
            dedupe_key=semantic_key,
        )
        try:
            result = self._speech_handler(speech_event)
            spoken = _spoken_from_handler_result(result)
        except Exception as exc:  # Audio is fail-open; the visual channel remains authoritative.
            _LOGGER.exception("Runtime TTS presentation failed")
            return PresentationResult(
                visual_text=visual_text,
                speech_attempted=True,
                spoken=False,
                preempt=preempt,
                deduplicated=False,
                presentation_ok=True,
                speech_error=type(exc).__name__,
            )

        if spoken:
            self._spoken_semantics.add(semantic_key)
        return PresentationResult(
            visual_text=visual_text,
            speech_attempted=True,
            spoken=spoken,
            preempt=preempt,
            deduplicated=False,
        )

    @staticmethod
    def _is_silent(event: RuntimeProgressEvent, category: str) -> bool:
        return event.importance is ProgressImportance.SILENT or category in _SILENT_CATEGORIES


def _normalize_category(category: str) -> str:
    return "_".join(str(category).casefold().replace("-", " ").split())[:80]


def _semantic_key(event: RuntimeProgressEvent, category: str, visual_text: str) -> str:
    evidence = "|".join(
        f"{item.source}:{item.source_id}" for item in event.evidence
    )
    payload = "|".join(
        (
            event.run_id.value,
            event.stage_id.value,
            event.event_type.value,
            category,
            " ".join(visual_text.casefold().split()),
            event.outcome.value if event.outcome is not None else "",
            evidence,
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"runtime:{digest}"


def _spoken_from_handler_result(result: object) -> bool:
    if isinstance(result, bool):
        return result
    if isinstance(result, tuple) and len(result) >= 2:
        return bool(result[1])
    return False
