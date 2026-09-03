from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[\wÀ-ÿ-]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SurfaceItem:
    item_id: str
    title: str
    category: str
    priority: int
    requires_decision: bool = False


@dataclass(frozen=True, slots=True)
class TodayView:
    primary_items: tuple[SurfaceItem, ...]
    briefing: str
    technical_diagnostics_visible: bool = False


def build_today_view(items: tuple[SurfaceItem, ...] | list[SurfaceItem]) -> TodayView:
    ranked = sorted(items, key=lambda item: (-item.priority, item.item_id))[:3]
    if ranked:
        titles = "; ".join(item.title for item in ranked)
        briefing = f"Aujourd’hui, voici ce qui compte maintenant : {titles}."
    else:
        briefing = "Aujourd’hui, rien d’urgent ne demande ton attention maintenant."
    return TodayView(tuple(ranked), briefing)


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    event_id: str
    event_type: str
    text: str


@dataclass(frozen=True, slots=True)
class ActivityView:
    lines: tuple[str, ...]
    current_text: str
    source_event_ids: tuple[str, ...]


def build_activity_view(events: tuple[ActivityEvent, ...] | list[ActivityEvent]) -> ActivityView:
    ordered = tuple(events)
    lines = tuple(event.text.strip() for event in ordered if event.text.strip())
    current = lines[-1] if lines else "Jarvis est prêt."
    return ActivityView(lines, current, tuple(event.event_id for event in ordered))


@dataclass(frozen=True, slots=True)
class DecisionItem:
    decision_id: str
    title: str
    recommendation: str
    source: str
    priority: int
    delay_cost: int = 0


@dataclass(frozen=True, slots=True)
class DecisionsView:
    items: tuple[DecisionItem, ...]


def build_decisions_view(items: tuple[DecisionItem, ...] | list[DecisionItem]) -> DecisionsView:
    ranked = sorted(
        items,
        key=lambda item: (-(item.priority + item.delay_cost), -item.priority, item.decision_id),
    )
    return DecisionsView(tuple(ranked))


@dataclass(frozen=True, slots=True)
class SituationSource:
    situation_id: str
    source_id: str
    source_name: str
    state: str
    next_step: str
    sequence: int
    completed: bool = False


@dataclass(frozen=True, slots=True)
class SituationCard:
    situation_id: str
    state: str
    next_step: str
    source_names: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SituationsView:
    active: tuple[SituationCard, ...]
    history: tuple[SituationCard, ...]


def build_situations_view(
    sources: tuple[SituationSource, ...] | list[SituationSource],
) -> SituationsView:
    grouped: dict[str, list[SituationSource]] = {}
    for source in sources:
        grouped.setdefault(source.situation_id, []).append(source)

    active: list[SituationCard] = []
    history: list[SituationCard] = []
    for situation_id, members in grouped.items():
        ordered = sorted(members, key=lambda item: (item.sequence, item.source_id))
        latest = ordered[-1]
        source_names = tuple(dict.fromkeys(item.source_name for item in ordered))
        card = SituationCard(
            situation_id=situation_id,
            state=latest.state,
            next_step=latest.next_step,
            source_names=source_names,
            source_ids=tuple(item.source_id for item in ordered),
        )
        (history if all(item.completed for item in ordered) else active).append(card)

    active.sort(key=lambda item: item.situation_id)
    history.sort(key=lambda item: item.situation_id)
    return SituationsView(tuple(active), tuple(history))


@dataclass(frozen=True, slots=True)
class SearchRecord:
    result_type: str
    record_id: str
    text: str
    source: str
    title: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    result_type: str
    record_id: str
    source: str
    title: str
    score: int


class UnifiedSearchIndex:
    """A read-only projection over records already supplied by shared domain indexes."""

    storage_name = "shared-index"

    def __init__(self, records: tuple[SearchRecord, ...] | list[SearchRecord]) -> None:
        self._records = tuple(records)

    def search(self, query: str, *, limit: int = 12) -> tuple[SearchResult, ...]:
        tokens = tuple(token.casefold() for token in _TOKEN_RE.findall(query) if len(token) >= 2)
        if not tokens:
            return ()
        ranked: list[SearchResult] = []
        for record in self._records:
            haystack = f"{record.title} {record.text} {record.source} {record.result_type}".casefold()
            score = sum(1 for token in tokens if token in haystack)
            if score:
                ranked.append(
                    SearchResult(
                        result_type=record.result_type,
                        record_id=record.record_id,
                        source=record.source,
                        title=record.title,
                        score=score,
                    )
                )
        ranked.sort(key=lambda item: (-item.score, item.result_type, item.record_id))
        return tuple(ranked[: max(1, min(int(limit), 50))])
