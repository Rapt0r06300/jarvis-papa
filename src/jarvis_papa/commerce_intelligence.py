from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.email_runtime import assess_email_trust
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    EntityKind,
    EntityRef,
    MatchState,
    NormalizedEvent,
    PriorityResult,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationDomain,
    VerifiedOutcome,
    apply_verified_outcome,
    correlation_keys,
    score_priority,
    transition_situation,
)

_PARIS = ZoneInfo("Europe/Paris")
_ORDER_RE = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
_TRACKING_RE = re.compile(
    r"\b(?:MR[A-Z0-9]{8,}|1Z[A-Z0-9]{16}|[A-Z]{2}\d{9}[A-Z]{2})\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_AMOUNT_RE = re.compile(r"Montant\s*:\s*(\d+(?:[,.]\d{1,2})?)\s*€", re.IGNORECASE)
_ITEM_RE = re.compile(r"Article\s*:\s*(.+?)(?=\.\s+Montant\s*:|$)", re.IGNORECASE)
_SELLER_RE = re.compile(
    r"Vendeur\s*:\s*(.+?)(?=\s+Date\s+de\s+commande\s*:|$)",
    re.IGNORECASE,
)
_PURCHASE_DATE_RE = re.compile(
    r"Date\s+de\s+commande\s*:\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_EXPECTED_DATE_RE = re.compile(
    r"(?:Nouvelle\s+)?Livraison\s+prévue\s*:\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


class OrderState(StrEnum):
    ORDERED = "ordered"
    PREPARING = "preparing"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    ISSUE = "issue"


class ShipmentState(StrEnum):
    LABEL_CREATED = "label_created"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    PICKUP_READY = "pickup_ready"
    DELIVERED = "delivered"
    COLLECTED = "collected"
    RETURNED = "returned"
    CANCELLED = "cancelled"


_ORDER_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.ORDERED: frozenset(
        {OrderState.PREPARING, OrderState.SHIPPED, OrderState.ISSUE}
    ),
    OrderState.PREPARING: frozenset({OrderState.SHIPPED, OrderState.ISSUE}),
    OrderState.SHIPPED: frozenset(
        {OrderState.IN_TRANSIT, OrderState.DELAYED, OrderState.DELIVERED, OrderState.ISSUE}
    ),
    OrderState.IN_TRANSIT: frozenset(
        {OrderState.DELAYED, OrderState.DELIVERED, OrderState.ISSUE}
    ),
    OrderState.DELAYED: frozenset(
        {OrderState.IN_TRANSIT, OrderState.DELIVERED, OrderState.ISSUE}
    ),
    OrderState.DELIVERED: frozenset(),
    OrderState.ISSUE: frozenset({OrderState.IN_TRANSIT, OrderState.DELIVERED}),
}

_SHIPMENT_TRANSITIONS: dict[ShipmentState, frozenset[ShipmentState]] = {
    ShipmentState.LABEL_CREATED: frozenset(
        {ShipmentState.IN_TRANSIT, ShipmentState.CANCELLED}
    ),
    ShipmentState.IN_TRANSIT: frozenset(
        {
            ShipmentState.DELAYED,
            ShipmentState.PICKUP_READY,
            ShipmentState.DELIVERED,
            ShipmentState.RETURNED,
        }
    ),
    ShipmentState.DELAYED: frozenset(
        {
            ShipmentState.IN_TRANSIT,
            ShipmentState.PICKUP_READY,
            ShipmentState.DELIVERED,
            ShipmentState.RETURNED,
        }
    ),
    ShipmentState.PICKUP_READY: frozenset(
        {ShipmentState.COLLECTED, ShipmentState.RETURNED}
    ),
    ShipmentState.DELIVERED: frozenset(),
    ShipmentState.COLLECTED: frozenset(),
    ShipmentState.RETURNED: frozenset(),
    ShipmentState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class EvidenceValue:
    value: object | None
    confidence: float = 0.0
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("evidence confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "provenance", tuple(self.provenance)[:16])

    @classmethod
    def unknown(cls) -> EvidenceValue:
        return cls(None, 0.0, ())

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "provenance": [item.to_dict() for item in self.provenance],
        }


@dataclass(frozen=True, slots=True)
class OrderRecord:
    order_id: EvidenceValue
    state: OrderState
    state_at: float
    purchase_date: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    items: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    amount: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    seller: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    shipment_id: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    invoice_id: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    refund_state: EvidenceValue = field(default_factory=EvidenceValue.unknown)

    def __post_init__(self) -> None:
        if float(self.state_at) <= 0:
            raise ValueError("order state timestamp must be positive")
        object.__setattr__(self, "state_at", float(self.state_at))

    def transitioned(self, state: OrderState, *, at: float) -> OrderRecord:
        target = OrderState(state)
        changed_at = float(at)
        if changed_at < self.state_at:
            raise ValueError("stale order transition")
        if target is self.state:
            return self
        if target not in _ORDER_TRANSITIONS[self.state]:
            raise ValueError(f"invalid order transition: {self.state.value} -> {target.value}")
        return replace(self, state=target, state_at=changed_at)


@dataclass(frozen=True, slots=True)
class ShipmentRecord:
    tracking_id: EvidenceValue
    state: ShipmentState
    state_at: float
    carrier: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    order_id: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    expected_delivery: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    actual_delivery: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    pickup_location: EvidenceValue = field(default_factory=EvidenceValue.unknown)
    pickup_deadline: EvidenceValue = field(default_factory=EvidenceValue.unknown)

    def __post_init__(self) -> None:
        if float(self.state_at) <= 0:
            raise ValueError("shipment state timestamp must be positive")
        object.__setattr__(self, "state_at", float(self.state_at))

    def transitioned(self, state: ShipmentState, *, at: float) -> ShipmentRecord:
        target = ShipmentState(state)
        changed_at = float(at)
        if changed_at < self.state_at:
            raise ValueError("stale shipment transition")
        if target is self.state:
            return self
        if target not in _SHIPMENT_TRANSITIONS[self.state]:
            raise ValueError(
                f"invalid shipment transition: {self.state.value} -> {target.value}"
            )
        return replace(self, state=target, state_at=changed_at)


@dataclass(frozen=True, slots=True)
class CommerceMatch:
    state: MatchState
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommerceParseResult:
    event: NormalizedEvent | None
    order: OrderRecord | None = None
    shipment: ShipmentRecord | None = None
    confidence: float = 0.0
    uncertain: bool = True
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommerceProjection:
    situation: Situation | None
    match_state: MatchState
    priority: PriorityResult | None = None
    inserted_event: bool = False


def match_order_shipment(order: OrderRecord, shipment: ShipmentRecord) -> CommerceMatch:
    order_id = _text_value(order.order_id)
    shipment_order_id = _text_value(shipment.order_id)
    tracking_id = _text_value(shipment.tracking_id)
    known_shipment_id = _text_value(order.shipment_id)
    if order_id and shipment_order_id and order_id.casefold() == shipment_order_id.casefold():
        return CommerceMatch(MatchState.CONFIRMED_MATCH, 0.99, ("same_order_id",))
    if tracking_id and known_shipment_id and tracking_id.casefold() == known_shipment_id.casefold():
        return CommerceMatch(MatchState.CONFIRMED_MATCH, 0.98, ("same_tracking_id",))
    if order_id and shipment_order_id and order_id.casefold() != shipment_order_id.casefold():
        return CommerceMatch(MatchState.POSSIBLE_MATCH, 0.1, ("conflicting_order_id",))
    return CommerceMatch(MatchState.POSSIBLE_MATCH, 0.35, ("no_strong_identifier",))


class AmazonCommerceParser:
    """Conservative Amazon mail adapter that emits canonical commerce evidence."""

    SOURCE_VERSION = "commerce-amazon-mail-v1"

    def parse(self, message: EmailMessage) -> CommerceParseResult:
        trust = assess_email_trust(message)
        signal_kinds = tuple(item.kind for item in trust.signals)
        blocking_signals = {"brand_domain_mismatch", "suspicious_link"}
        if blocking_signals.intersection(signal_kinds):
            return CommerceParseResult(
                event=None,
                confidence=0.25,
                uncertain=True,
                reasons=signal_kinds or ("untrusted_sender",),
            )

        text = f"{message.subject}\n{message.body}"
        lower = text.casefold()
        order_id = _first(_ORDER_RE, text)
        tracking_id = _first(_TRACKING_RE, text)
        event_type = self._event_type(lower, order_id=order_id, tracking_id=tracking_id)
        if not event_type:
            return CommerceParseResult(
                event=None,
                confidence=0.4,
                uncertain=True,
                reasons=("unrecognized_commerce_message",),
            )
        if event_type == "order_confirmed" and not order_id:
            return CommerceParseResult(
                event=None,
                confidence=0.35,
                uncertain=True,
                reasons=("missing_order_identifier",),
            )
        if event_type != "order_confirmed" and not (order_id or tracking_id):
            return CommerceParseResult(
                event=None,
                confidence=0.35,
                uncertain=True,
                reasons=("missing_commerce_identifier",),
            )

        provenance = (message.provenance,)
        confidence = 0.96 if not trust.requires_verification else 0.82
        refs = tuple(
            item
            for item in (
                f"order:{order_id}" if order_id else "",
                f"tracking:{tracking_id}" if tracking_id else "",
            )
            if item
        )
        event = NormalizedEvent(
            source="amazon_email",
            source_event_id=message.message_id,
            event_type=event_type,
            occurred_at=message.received_at,
            observed_at=message.received_at,
            subject_refs=refs,
            payload_summary=self._summary(event_type, order_id, tracking_id),
            provenance=provenance,
            confidence=confidence,
            source_version=self.SOURCE_VERSION,
        )
        order = (
            self._order_record(message, order_id, provenance)
            if event_type == "order_confirmed"
            else None
        )
        shipment = (
            self._shipment_record(message, event_type, order_id, tracking_id, provenance)
            if event_type != "order_confirmed"
            else None
        )
        return CommerceParseResult(
            event=event,
            order=order,
            shipment=shipment,
            confidence=confidence,
            uncertain=False,
            reasons=signal_kinds,
        )

    @staticmethod
    def _event_type(lower: str, *, order_id: str, tracking_id: str) -> str:
        if any(
            term in lower
            for term in ("a été livré", "a ete livre", "est livré", "est livre")
        ):
            return "shipment_delivered"
        if any(term in lower for term in ("retard", "retardé", "retarde")):
            return "shipment_delayed"
        if any(term in lower for term in ("expédi", "expedi", "en transit")):
            return "shipment_update"
        if order_id and any(
            term in lower
            for term in ("merci pour votre commande", "commande amazon", "date de commande")
        ):
            return "order_confirmed"
        if tracking_id and "colis" in lower:
            return "shipment_update"
        return ""

    @staticmethod
    def _summary(event_type: str, order_id: str, tracking_id: str) -> str:
        label = {
            "order_confirmed": "Commande confirmée",
            "shipment_update": "Colis expédié ou en transit",
            "shipment_delayed": "Retard de livraison signalé",
            "shipment_delivered": "Livraison signalée",
        }.get(event_type, "Mise à jour de commande")
        refs = " · ".join(item for item in (order_id, tracking_id) if item)
        return f"{label} · {refs}" if refs else label

    @staticmethod
    def _order_record(
        message: EmailMessage,
        order_id: str,
        provenance: tuple[ProvenanceRef, ...],
    ) -> OrderRecord:
        body = message.body
        amount_match = _AMOUNT_RE.search(body)
        amount = (
            float(amount_match.group(1).replace(",", ".")) if amount_match is not None else None
        )
        item_match = _ITEM_RE.search(body)
        items = (item_match.group(1).strip(),) if item_match is not None else None
        seller_match = _SELLER_RE.search(body)
        seller = seller_match.group(1).strip() if seller_match is not None else None
        date_match = _PURCHASE_DATE_RE.search(body)
        purchase_date = date_match.group(1) if date_match is not None else None
        return OrderRecord(
            order_id=_fact(order_id, 0.99, provenance),
            state=OrderState.ORDERED,
            state_at=message.received_at,
            purchase_date=_optional_fact(purchase_date, 0.96, provenance),
            items=_optional_fact(items, 0.9, provenance),
            amount=_optional_fact(amount, 0.96, provenance),
            seller=_optional_fact(seller, 0.9, provenance),
        )

    @staticmethod
    def _shipment_record(
        message: EmailMessage,
        event_type: str,
        order_id: str,
        tracking_id: str,
        provenance: tuple[ProvenanceRef, ...],
    ) -> ShipmentRecord:
        state = {
            "shipment_delayed": ShipmentState.DELAYED,
            "shipment_delivered": ShipmentState.DELIVERED,
        }.get(event_type, ShipmentState.IN_TRANSIT)
        expected_match = _EXPECTED_DATE_RE.search(message.body)
        expected = expected_match.group(1) if expected_match is not None else None
        actual = (
            datetime.fromtimestamp(message.received_at, _PARIS).date().isoformat()
            if state is ShipmentState.DELIVERED
            else None
        )
        return ShipmentRecord(
            tracking_id=_optional_fact(tracking_id or None, 0.98, provenance),
            state=state,
            state_at=message.received_at,
            order_id=_optional_fact(order_id or None, 0.99, provenance),
            expected_delivery=_optional_fact(expected, 0.9, provenance),
            actual_delivery=_optional_fact(actual, 0.9, provenance),
        )


class CommerceProjector:
    """Project commerce evidence into the existing SituationStore, idempotently."""

    def __init__(self, store: SituationStore) -> None:
        self.store = store

    def project(
        self,
        parsed: CommerceParseResult,
        *,
        now: float | None = None,
    ) -> CommerceProjection:
        event = parsed.event
        if event is None:
            return CommerceProjection(None, MatchState.POSSIBLE_MATCH)

        inserted = self.store.ingest_event(event)
        entities = self._entities(parsed, event)
        keys = correlation_keys(event, entities=entities)
        situation = self.store.find_situation_by_keys(keys)
        match_state = MatchState.POSSIBLE_MATCH
        if situation is None:
            situation = self._new_situation(parsed, event)
        elif parsed.shipment is not None and situation.domain is SituationDomain.ORDER:
            shipment_order = _text_value(parsed.shipment.order_id)
            stored_order = str(situation.metadata.get("order_id") or "")
            if (
                shipment_order
                and stored_order
                and shipment_order.casefold() == stored_order.casefold()
            ):
                match_state = MatchState.CONFIRMED_MATCH
            else:
                match_state = MatchState.LIKELY_MATCH
        elif parsed.order is not None:
            match_state = MatchState.CONFIRMED_MATCH

        for entity in entities:
            self.store.save_entity(entity)
            if entity.entity_id not in situation.entity_ids:
                situation.entity_ids.append(entity.entity_id)

        added = situation.add_event(event)
        self._apply_facts(situation, parsed)
        self._apply_lifecycle(situation, parsed, event, added=added)
        self.store.save_situation(situation, correlation_keys=keys)
        self.store.mark_event_processed(event.identity_key)
        priority = score_priority(situation, now=now)
        return CommerceProjection(situation, match_state, priority, inserted)

    @staticmethod
    def _new_situation(parsed: CommerceParseResult, event: NormalizedEvent) -> Situation:
        order_id = _parsed_order_id(parsed)
        tracking_id = _parsed_tracking_id(parsed)
        if order_id:
            title = f"Commande {order_id}"
            domain = SituationDomain.ORDER
            state = "ordered" if parsed.order is not None else "shipped"
        else:
            title = f"Colis {tracking_id}" if tracking_id else "Suivi de colis"
            domain = SituationDomain.SHIPMENT
            state = {
                "shipment_delayed": "delayed",
                "shipment_delivered": "delivered",
            }.get(event.event_type, "in_transit")
        return Situation.create(title, domain=domain, state=state, confidence=event.confidence)

    @staticmethod
    def _entities(
        parsed: CommerceParseResult,
        event: NormalizedEvent,
    ) -> tuple[EntityRef, ...]:
        entities: list[EntityRef] = []
        order_id = _parsed_order_id(parsed)
        tracking_id = _parsed_tracking_id(parsed)
        if order_id:
            entities.append(EntityRef(EntityKind.ORDER, order_id, provenance=event.provenance))
        if tracking_id:
            entities.append(
                EntityRef(EntityKind.SHIPMENT, tracking_id, provenance=event.provenance)
            )
        return tuple(entities)

    @staticmethod
    def _apply_facts(situation: Situation, parsed: CommerceParseResult) -> None:
        if parsed.order is not None:
            _set_metadata(situation, "order_id", parsed.order.order_id.value)
            _set_metadata(situation, "purchase_date", parsed.order.purchase_date.value)
            _set_metadata(situation, "items", parsed.order.items.value)
            _set_metadata(situation, "amount", parsed.order.amount.value)
            _set_metadata(situation, "seller", parsed.order.seller.value)
        if parsed.shipment is not None:
            _set_metadata(situation, "order_id", parsed.shipment.order_id.value)
            _set_metadata(situation, "tracking_id", parsed.shipment.tracking_id.value)
            _set_metadata(situation, "carrier", parsed.shipment.carrier.value)
            _set_metadata(
                situation,
                "expected_delivery",
                parsed.shipment.expected_delivery.value,
            )
            expected = _text_value(parsed.shipment.expected_delivery)
            if expected:
                deadline = _date_timestamp(expected)
                if deadline is not None:
                    situation.metadata["deadline_at"] = deadline

    @staticmethod
    def _apply_lifecycle(
        situation: Situation,
        parsed: CommerceParseResult,
        event: NormalizedEvent,
        *,
        added: bool,
    ) -> None:
        if event.event_type == "order_confirmed":
            if situation.domain is SituationDomain.ORDER and situation.state == "new":
                _safe_transition(situation, "ordered", "order confirmation", event.occurred_at)
            return

        shipment = parsed.shipment
        if shipment is None:
            return
        situation.metadata["shipment_state"] = shipment.state.value
        if event.event_type == "shipment_update":
            situation.action_state = ActionState.READ_ONLY
            situation.responsibility = Responsibility.WAITING
            if situation.domain is SituationDomain.ORDER and situation.state in {
                "ordered",
                "processing",
            }:
                _safe_transition(situation, "shipped", "shipment evidence", event.occurred_at)
            elif situation.domain is SituationDomain.SHIPMENT and situation.state in {
                "new",
                "label_created",
            }:
                _safe_transition(situation, "in_transit", "shipment evidence", event.occurred_at)
            return

        if event.event_type == "shipment_delayed":
            situation.metadata["delay_evidence"] = "explicit_source"
            situation.action_state = ActionState.VERIFY
            situation.responsibility = Responsibility.FATHER_MUST_ACT
            if situation.domain is SituationDomain.SHIPMENT and situation.state == "in_transit":
                _safe_transition(situation, "delayed", "explicit delay evidence", event.occurred_at)
            return

        if event.event_type != "shipment_delivered" or event.confidence < 0.8 or not added:
            return
        can_transition_to_delivered = (
            situation.domain is SituationDomain.ORDER and situation.state == "shipped"
        ) or (
            situation.domain is SituationDomain.SHIPMENT
            and situation.state in {"in_transit", "delayed"}
        )
        if can_transition_to_delivered:
            _safe_transition(
                situation,
                "delivered",
                "verified delivery evidence",
                event.occurred_at,
            )
        outcome = VerifiedOutcome.create(
            action_id=f"commerce:{event.identity_key[:48]}",
            outcome_type="parcel_delivered",
            verified=True,
            proof={"event_key": event.identity_key, "confidence": event.confidence},
            occurred_at=event.occurred_at,
        )
        apply_verified_outcome(situation, outcome)


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(0).strip() if match is not None else ""


def _fact(
    value: object,
    confidence: float,
    provenance: tuple[ProvenanceRef, ...],
) -> EvidenceValue:
    return EvidenceValue(value, confidence, provenance)


def _optional_fact(
    value: object | None,
    confidence: float,
    provenance: tuple[ProvenanceRef, ...],
) -> EvidenceValue:
    return (
        EvidenceValue(value, confidence, provenance)
        if value is not None
        else EvidenceValue.unknown()
    )


def _text_value(value: EvidenceValue) -> str:
    return str(value.value).strip() if value.value is not None else ""


def _parsed_order_id(parsed: CommerceParseResult) -> str:
    if parsed.order is not None:
        return _text_value(parsed.order.order_id)
    if parsed.shipment is not None:
        return _text_value(parsed.shipment.order_id)
    return ""


def _parsed_tracking_id(parsed: CommerceParseResult) -> str:
    return _text_value(parsed.shipment.tracking_id) if parsed.shipment is not None else ""


def _date_timestamp(value: str) -> float | None:
    if _DATE_RE.fullmatch(value.strip()) is None:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=_PARIS).timestamp()
    except ValueError:
        return None


def _set_metadata(situation: Situation, key: str, value: object | None) -> None:
    if value is not None:
        situation.metadata[key] = value


def _safe_transition(situation: Situation, state: str, reason: str, at: float) -> None:
    try:
        transition_situation(situation, state, reason=reason, changed_at=at)
    except ValueError:
        return
