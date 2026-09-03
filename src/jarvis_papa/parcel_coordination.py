from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis_papa.commerce_intelligence import (
    CommerceMatch,
    CommerceParseResult,
    EvidenceValue,
    OrderRecord,
    ShipmentRecord,
    ShipmentState,
    match_order_shipment,
)
from jarvis_papa.situations import (
    ActionState,
    MatchState,
    NormalizedEvent,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationDomain,
    SituationTask,
    score_priority,
)

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True, slots=True)
class TrackingReference:
    raw: str
    normalized: str
    carrier: str
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True, slots=True)
class TrackingMergeResult:
    reference: TrackingReference
    conflict: bool


def normalize_tracking_reference(
    raw_tracking: str,
    *,
    carrier: str,
    provenance: ProvenanceRef,
) -> TrackingReference:
    raw = str(raw_tracking).strip()[:240]
    normalized = _NON_ALNUM.sub("", raw.upper())[:160]
    if not normalized:
        raise ValueError("tracking reference cannot be empty")
    clean_carrier = " ".join(str(carrier).split()).strip()[:120]
    return TrackingReference(raw, normalized, clean_carrier, (provenance,))


def merge_tracking_references(
    current: TrackingReference,
    incoming: TrackingReference,
) -> TrackingMergeResult:
    same_tracking = current.normalized == incoming.normalized
    carrier_conflict = bool(
        current.carrier
        and incoming.carrier
        and current.carrier.casefold() != incoming.carrier.casefold()
    )
    if not same_tracking or carrier_conflict:
        return TrackingMergeResult(current, True)
    provenance = tuple(dict.fromkeys((*current.provenance, *incoming.provenance)))
    carrier = current.carrier or incoming.carrier
    return TrackingMergeResult(
        TrackingReference(current.raw, current.normalized, carrier, provenance),
        False,
    )


def build_carrier_tracking_update(
    *,
    raw_tracking: str,
    carrier: str,
    state: ShipmentState,
    source: str,
    source_event_id: str,
    occurred_at: float,
    observed_at: float,
    provenance: ProvenanceRef,
) -> CommerceParseResult:
    reference = normalize_tracking_reference(
        raw_tracking,
        carrier=carrier,
        provenance=provenance,
    )
    event = NormalizedEvent(
        source=source,
        source_event_id=source_event_id,
        event_type="carrier_tracking_update",
        occurred_at=occurred_at,
        observed_at=observed_at,
        subject_refs=(f"tracking:{reference.normalized}",),
        payload_summary=(
            f"Mise à jour transporteur · {reference.carrier or source} · "
            f"{reference.normalized} · {ShipmentState(state).value}"
        ),
        provenance=(provenance,),
        confidence=0.96,
        source_version="carrier-tracking-v1",
    )
    shipment = ShipmentRecord(
        tracking_id=EvidenceValue(reference.normalized, 0.99, reference.provenance),
        state=ShipmentState(state),
        state_at=float(occurred_at),
        carrier=EvidenceValue(reference.carrier, 0.96, reference.provenance),
    )
    return CommerceParseResult(
        event=event,
        shipment=shipment,
        confidence=0.96,
        uncertain=False,
    )


def correlate_order_carrier(order: OrderRecord, shipment: ShipmentRecord) -> CommerceMatch:
    base = match_order_shipment(order, shipment)
    if base.state is MatchState.CONFIRMED_MATCH:
        return base

    known_tracking = _normalized_evidence(order.shipment_id)
    shipment_tracking = _normalized_evidence(shipment.tracking_id)
    if known_tracking and shipment_tracking:
        if known_tracking == shipment_tracking:
            return CommerceMatch(
                MatchState.CONFIRMED_MATCH,
                0.99,
                ("same_normalized_tracking_id",),
            )
        return CommerceMatch(
            MatchState.POSSIBLE_MATCH,
            0.1,
            ("conflicting_tracking_id",),
        )

    order_date = _text_evidence(order.purchase_date)
    shipment_date = _text_evidence(shipment.expected_delivery)
    if order_date and shipment_date and order_date == shipment_date:
        return CommerceMatch(
            MatchState.LIKELY_MATCH,
            0.55,
            ("date_only",),
        )
    return CommerceMatch(
        MatchState.POSSIBLE_MATCH,
        0.3,
        ("no_strong_identifier",),
    )


def correlate_amazon_mondial(
    amazon_shipment: ShipmentRecord,
    mondial_shipment: ShipmentRecord,
) -> CommerceMatch:
    amazon_tracking = _normalized_evidence(amazon_shipment.tracking_id)
    mondial_tracking = _normalized_evidence(mondial_shipment.tracking_id)
    if amazon_tracking and mondial_tracking:
        if amazon_tracking == mondial_tracking:
            return CommerceMatch(
                MatchState.CONFIRMED_MATCH,
                0.99,
                ("same_normalized_tracking_id",),
            )
        return CommerceMatch(
            MatchState.POSSIBLE_MATCH,
            0.1,
            ("conflicting_tracking_id",),
        )
    amazon_order = _text_evidence(amazon_shipment.order_id)
    mondial_order = _text_evidence(mondial_shipment.order_id)
    if amazon_order and mondial_order and amazon_order.casefold() == mondial_order.casefold():
        return CommerceMatch(MatchState.CONFIRMED_MATCH, 0.98, ("same_order_id",))
    return CommerceMatch(MatchState.POSSIBLE_MATCH, 0.35, ("weak_cross_source_evidence",))


class PickupReminderPolicy:
    """Deadline-aware reminder policy with acknowledgement and snooze suppression."""

    def __init__(self) -> None:
        self._last_reminder: dict[str, float] = {}
        self._acknowledged: dict[str, float] = {}
        self._snoozed_until: dict[str, float] = {}

    @staticmethod
    def cadence_seconds(*, deadline_at: float, now: float) -> float:
        remaining = float(deadline_at) - float(now)
        if remaining <= 6 * 3_600:
            return 3_600.0
        if remaining <= 24 * 3_600:
            return 2 * 3_600.0
        if remaining <= 72 * 3_600:
            return 8 * 3_600.0
        return 24 * 3_600.0

    def should_remind(self, parcel_id: str, *, deadline_at: float, now: float) -> bool:
        key = _parcel_key(parcel_id)
        current = float(now)
        if self._snoozed_until.get(key, 0.0) > current:
            return False
        anchors = (
            self._last_reminder.get(key, 0.0),
            self._acknowledged.get(key, 0.0),
        )
        last_activity = max(anchors)
        if last_activity <= 0:
            return True
        cadence = self.cadence_seconds(deadline_at=deadline_at, now=current)
        return current - last_activity >= cadence

    def record_reminder(self, parcel_id: str, *, at: float) -> None:
        self._last_reminder[_parcel_key(parcel_id)] = float(at)

    def acknowledge(self, parcel_id: str, *, at: float) -> None:
        self._acknowledged[_parcel_key(parcel_id)] = float(at)

    def snooze(self, parcel_id: str, *, until: float) -> None:
        self._snoozed_until[_parcel_key(parcel_id)] = float(until)


@dataclass(frozen=True, slots=True)
class OrderBriefingItem:
    order_id: str
    state: str
    confidence: float
    timeline_events: int
    situation_id: str


def build_order_briefing(situations: list[Situation] | tuple[Situation, ...]) -> tuple[OrderBriefingItem, ...]:
    selected: dict[str, Situation] = {}
    for situation in situations:
        if situation.domain not in {SituationDomain.ORDER, SituationDomain.SHIPMENT, SituationDomain.REFUND}:
            continue
        order_id = str(situation.metadata.get("order_id") or "").strip()
        if not order_id:
            order_id = str(situation.metadata.get("tracking_id") or situation.situation_id)
        previous = selected.get(order_id)
        if previous is None or situation.updated_at >= previous.updated_at:
            selected[order_id] = situation

    items = [
        OrderBriefingItem(
            order_id=order_id,
            state=situation.state,
            confidence=float(situation.confidence),
            timeline_events=len(situation.timeline),
            situation_id=situation.situation_id,
        )
        for order_id, situation in selected.items()
    ]
    items.sort(key=lambda item: item.order_id)
    return tuple(items)


def run_parcel_benchmark(*, now: float) -> dict[str, object]:
    """Reproducible synthetic E2E ground truth; contains no user-derived data."""

    current = float(now)
    situation = Situation.create(
        "Commande TEST-ORDER-001 — retrait fixture",
        domain=SituationDomain.SHIPMENT,
        state="pickup_ready",
        confidence=0.96,
    )
    situation.action_state = ActionState.PICKUP
    situation.responsibility = Responsibility.FATHER_MUST_ACT
    situation.metadata.update(
        {
            "order_id": "TEST-ORDER-001",
            "tracking_id": "MRTEST000001FR",
            "carrier": "Mondial Relay Fixture",
            "deadline_at": current + 6 * 3_600,
            "pickup_deadline": current + 6 * 3_600,
            "pickup_expiring": True,
            "pickup_code_available": True,
            "pickup_qr_available": False,
            "fixture_domain": "example.test",
        }
    )
    situation.add_task(
        SituationTask.create(
            "Retirer le colis fixture",
            action_state=ActionState.PICKUP,
            responsibility=Responsibility.FATHER_MUST_ACT,
            due_at=current + 6 * 3_600,
        )
    )
    priority = score_priority(situation, now=current)
    ground_truth: dict[str, object] = {
        "correlation": "confirmed",
        "status": "pickup_ready",
        "deadline": current + 6 * 3_600,
        "code_available": True,
        "qr_available": False,
        "tasks": 1,
        "priority": priority.band,
    }
    return {
        "scenario_version": "parcel-e2e-v1",
        "synthetic_only": True,
        "contains_real_personal_data": False,
        "pickup_situations": 1,
        "correct_priority": priority.band in {"A_FAIRE", "URGENT"},
        "priority_score": priority.score,
        "ground_truth": ground_truth,
    }


def _normalized_evidence(value: EvidenceValue) -> str:
    if value.value is None:
        return ""
    return _NON_ALNUM.sub("", str(value.value).upper())[:160]


def _text_evidence(value: EvidenceValue) -> str:
    return str(value.value).strip() if value.value is not None else ""


def _parcel_key(value: str) -> str:
    key = _NON_ALNUM.sub("", str(value).upper())[:160]
    if not key:
        raise ValueError("parcel id cannot be empty")
    return key
