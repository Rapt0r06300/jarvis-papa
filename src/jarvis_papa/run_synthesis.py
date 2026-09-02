from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    ProvenanceRef,
    Responsibility,
    Situation,
    SourceConnectionState,
    SourceHealth,
    score_priority,
)


class FreshnessState(StrEnum):
    CURRENT = "CURRENT"
    LAST_KNOWN = "LAST_KNOWN"


@dataclass(frozen=True, slots=True)
class ExternalFactPresentation:
    text: str
    source: str
    observed_at: float
    freshness: FreshnessState
    display_text: str


@dataclass(frozen=True, slots=True)
class SourceFailurePresentation:
    source: str
    user_message: str
    technical_detail: str


@dataclass(frozen=True, slots=True)
class RunSynthesis:
    processed_events: int
    important_situations: tuple[str, ...]
    decisions_for_robert: tuple[str, ...]
    degraded_sources: tuple[str, ...]
    text: str


class RunSynthesizer:
    """Build Robert-facing summaries strictly from persisted situation facts."""

    def __init__(self, store: SituationStore) -> None:
        self._store = store

    def build(self, *, source_health: tuple[SourceHealth, ...] = ()) -> RunSynthesis:
        situations = tuple(self._store.list_situations(limit=500))
        processed_events = sum(len(item.event_ids) for item in situations)
        important = tuple(
            item.title
            for item in situations
            if score_priority(item).score >= 45
        )
        decisions = tuple(
            item.title
            for item in situations
            if item.responsibility is Responsibility.FATHER_MUST_ACT
            or item.action_state
            not in {
                ActionState.NO_ACTION,
                ActionState.READ_ONLY,
                ActionState.WAIT_FOR_OTHER_PARTY,
            }
        )
        degraded = tuple(
            health.source
            for health in source_health
            if health.state is not SourceConnectionState.CONNECTED
        )
        text = self._render_text(
            situations,
            processed_events=processed_events,
            important=important,
            decisions=decisions,
            degraded=degraded,
        )
        return RunSynthesis(
            processed_events=processed_events,
            important_situations=important,
            decisions_for_robert=decisions,
            degraded_sources=degraded,
            text=text,
        )

    @staticmethod
    def _render_text(
        situations: tuple[Situation, ...],
        *,
        processed_events: int,
        important: tuple[str, ...],
        decisions: tuple[str, ...],
        degraded: tuple[str, ...],
    ) -> str:
        lines = [f"Synthèse : {processed_events} information(s) persistée(s) traitée(s)."]
        for situation in situations:
            latest = situation.timeline[-1].summary if situation.timeline else situation.state
            lines.append(f"- {situation.title} : {latest}")
        if important:
            lines.append("Priorités : " + "; ".join(important) + ".")
        if decisions:
            lines.append("Décision ou action attendue de Robert : " + "; ".join(decisions) + ".")
        if degraded:
            lines.append("Sources non actualisées : " + "; ".join(degraded) + ".")
        return "\n".join(lines)


def humanize_source_failure(source: str, technical_detail: str) -> SourceFailurePresentation:
    clean_source = " ".join(str(source).split()).strip()[:120] or "cette source"
    detail = str(technical_detail).strip()[:8000]
    return SourceFailurePresentation(
        source=clean_source,
        user_message=(
            f"Je n'ai pas pu actualiser {clean_source}. "
            "Je continue avec les informations déjà disponibles."
        ),
        technical_detail=detail,
    )


def render_external_fact(
    text: str,
    *,
    provenance: ProvenanceRef,
    health: SourceHealth | None,
) -> ExternalFactPresentation:
    if not isinstance(provenance, ProvenanceRef):
        raise TypeError("external facts require ProvenanceRef")
    clean_text = " ".join(str(text).split()).strip()[:1500]
    if not clean_text:
        raise ValueError("external fact text is required")
    freshness = _freshness_state(provenance, health)
    observed = _format_observed_at(provenance.observed_at)
    if freshness is FreshnessState.CURRENT:
        display = f"Information actuelle (observée {observed}) : {clean_text}"
    else:
        display = f"Dernière information connue (observée {observed}) : {clean_text}"
    return ExternalFactPresentation(
        text=clean_text,
        source=provenance.source,
        observed_at=provenance.observed_at,
        freshness=freshness,
        display_text=display,
    )


def _freshness_state(
    provenance: ProvenanceRef,
    health: SourceHealth | None,
) -> FreshnessState:
    if health is None:
        return FreshnessState.LAST_KNOWN
    same_source = health.source.casefold() == provenance.source.casefold()
    current_check = health.checked_at >= provenance.observed_at
    if same_source and current_check and health.state is SourceConnectionState.CONNECTED:
        return FreshnessState.CURRENT
    return FreshnessState.LAST_KNOWN


def _format_observed_at(observed_at: float) -> str:
    value = datetime.fromtimestamp(float(observed_at), UTC)
    return value.strftime("%Y-%m-%d %H:%M UTC")
