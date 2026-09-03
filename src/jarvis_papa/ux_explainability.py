from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    kind: str
    label: str
    occurred_at: datetime
    source_id: str
    source_expandable: bool = True


def build_timeline(events: tuple[TimelineEvent, ...]) -> tuple[TimelineEvent, ...]:
    """Return normalized chronological milestones while retaining source provenance."""
    return tuple(sorted(events, key=lambda event: (event.occurred_at, event.kind, event.source_id)))


def explain_why(factors: Mapping[str, str]) -> str:
    """Explain the dominant surfaced reason from supplied evidence only."""
    deadline = factors.get("pickup_deadline")
    if deadline:
        source = factors.get("source")
        suffix = f" selon {source}" if source else ""
        return f"Je te le montre car le retrait du colis est prévu avant {deadline}{suffix}."

    awaiting = factors.get("buyer_awaiting_reply")
    if awaiting:
        return f"Je te le montre car l’acheteur attend une réponse depuis {awaiting}."

    deadline = factors.get("deadline")
    if deadline:
        return f"Je te le montre car une échéance réelle est prévue {deadline}."

    evidence = factors.get("evidence")
    if evidence:
        return f"Je te le montre à cause de cet élément vérifié : {evidence}."

    return "Je n’ai pas assez d’éléments vérifiés pour expliquer pourquoi cet élément est prioritaire."


def humanize_confidence(statement: str, confidence: float) -> str:
    """Map confidence to concise natural French without overstating weak evidence."""
    normalized = statement.strip()
    if not normalized:
        return "Je n’ai pas assez d’éléments pour conclure."
    normalized = normalized[0].upper() + normalized[1:]
    confidence = max(0.0, min(1.0, confidence))
    if confidence >= 0.95:
        return f"{normalized}."
    if confidence >= 0.60:
        return f"Je pense que c’est {statement.strip()}, mais je préfère le vérifier."
    return f"Ce lien reste incertain : {statement.strip()}. Je ne suis pas certain."


@dataclass(frozen=True, slots=True)
class LayoutCertification:
    scale_percent: int
    viewport: tuple[int, int]
    primary_actions_accessible: bool
    text_clipped: bool
    focus_visible: bool
    navigation_usable: bool
    cards_usable: bool
    dialog_fits: bool
    scrolling_required: bool


def certify_layout(*, scale_percent: int, viewport: tuple[int, int]) -> LayoutCertification:
    """Evaluate the Robert-first layout envelope at Windows scaling factors.

    The contract models the actual responsive geometry used by the primary desktop surfaces:
    navigation and cards may scroll, while the decision dialog must fit the scaled viewport.
    """
    if scale_percent <= 0:
        raise ValueError("scale_percent must be positive")
    width, height = viewport
    if width <= 0 or height <= 0:
        raise ValueError("viewport dimensions must be positive")

    scale = scale_percent / 100.0
    logical_width = width / scale
    logical_height = height / scale

    min_navigation_width = 720.0
    min_card_width = 620.0
    min_dialog_width = 520.0
    min_dialog_height = 430.0
    min_focus_gutter = 8.0

    navigation_usable = logical_width >= min_navigation_width
    cards_usable = logical_width >= min_card_width
    dialog_fits = logical_width >= min_dialog_width and logical_height >= min_dialog_height
    focus_visible = logical_width - min_card_width >= min_focus_gutter
    primary_actions_accessible = cards_usable and dialog_fits
    text_clipped = not cards_usable
    scrolling_required = logical_height < 640.0

    return LayoutCertification(
        scale_percent=scale_percent,
        viewport=viewport,
        primary_actions_accessible=primary_actions_accessible,
        text_clipped=text_clipped,
        focus_visible=focus_visible,
        navigation_usable=navigation_usable,
        cards_usable=cards_usable,
        dialog_fits=dialog_fits,
        scrolling_required=scrolling_required,
    )
