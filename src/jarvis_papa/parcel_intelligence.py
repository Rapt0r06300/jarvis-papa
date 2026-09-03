from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from jarvis_papa.commerce_intelligence import (
    EvidenceValue,
    OrderRecord,
    ShipmentRecord,
    ShipmentState,
)
from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.email_runtime import assess_email_trust
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    EntityKind,
    EntityRef,
    MatchState,
    NormalizedEvent,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationDomain,
    VerifiedOutcome,
    apply_verified_outcome,
    correlation_keys,
)

_PARIS = ZoneInfo("Europe/Paris")
_TRACKING_RE = re.compile(r"\bMR[A-Z0-9]{8,}\b", re.IGNORECASE)
_POINT_RE = re.compile(
    r"Point\s+Relais\s*:\s*(.+?)(?=\.\s+(?:Votre|Ce)\s+colis|$)",
    re.IGNORECASE,
)
_PICKUP_DURATION_RE = re.compile(
    r"(?:pendant|durant)\s+(\d{1,2})\s+jours?\b",
    re.IGNORECASE,
)
_EXPLICIT_DATE_RE = re.compile(
    r"(?:jusqu(?:'|’)au|avant\s+le|date\s+limite\s*:)\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"(?:code\s+(?:de\s+)?retrait|code\s+colis)\s*:\s*([A-Z0-9-]{4,20})\b",
    re.IGNORECASE,
)
_QR_URL_RE = re.compile(
    r"(?:QR(?:\s+code)?(?:\s+de\s+retrait)?\s*:)\s*(https?://[^\s<>]+)",
    re.IGNORECASE,
)


class RefundState(StrEnum):
    RETURN_STARTED = "return_started"
    RETURNED = "returned"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    ISSUE = "issue"


@dataclass(frozen=True, slots=True)
class RefundExpectation:
    amount: EvidenceValue
    expected_by: EvidenceValue
    state: RefundState = RefundState.REFUND_PENDING
    provenance: tuple[ProvenanceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class RefundConfirmation:
    matched: bool
    state: RefundState
    expected_amount: float | None
    expected_by: str | None
    provenance: tuple[ProvenanceRef, ...]


def confirm_refund(
    situation: Situation,
    expectation: RefundExpectation,
    *,
    credited_amount: float,
    observed_at: float,
    provenance: ProvenanceRef,
) -> RefundConfirmation:
    expected_amount = _float_value(expectation.amount)
    expected_by = _string_value(expectation.expected_by)
    amount_matches = (
        expected_amount is not None and abs(float(credited_amount) - expected_amount) <= 0.01
    )
    provenance_chain = tuple(dict.fromkeys((*expectation.provenance, provenance)))
    if expectation.state is not RefundState.REFUND_PENDING or not amount_matches:
        return RefundConfirmation(
            False,
            expectation.state,
            expected_amount,
            expected_by or None,
            provenance_chain,
        )

    outcome = VerifiedOutcome.create(
        action_id=f"refund:{provenance.source_id}",
        outcome_type="refund_confirmed",
        verified=True,
        proof={
            "amount": round(float(credited_amount), 2),
            "source": provenance.source,
            "source_id": provenance.source_id,
        },
        occurred_at=observed_at,
    )
    apply_verified_outcome(situation, outcome)
    return RefundConfirmation(
        True,
        RefundState.REFUNDED,
        expected_amount,
        expected_by or None,
        provenance_chain,
    )


class DocumentSearch(Protocol):
    def search(
        self,
        query: str,
        *,
        limit: int = 6,
        refresh: bool = True,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class DocumentLinkCandidate:
    path: str
    name: str
    location: str
    state: MatchState
    confidence: float
    evidence: tuple[str, ...]
    snippet: str


class OrderDocumentLinker:
    """Use the existing DocumentRAG search surface and score returned evidence."""

    def __init__(self, rag: DocumentSearch) -> None:
        self.rag = rag

    def find_candidates(self, order: OrderRecord, *, limit: int = 6) -> tuple[DocumentLinkCandidate, ...]:
        query = self._query(order)
        response = self.rag.search(query, limit=limit, refresh=True)
        raw_results = response.get("results") if isinstance(response, dict) else None
        if not isinstance(raw_results, list):
            return ()
        candidates: list[DocumentLinkCandidate] = []
        for raw in raw_results[: max(1, min(int(limit), 12))]:
            if not isinstance(raw, dict):
                continue
            snippet = str(raw.get("snippet") or "")
            name = str(raw.get("name") or "")
            haystack = f"{name} {snippet}".casefold()
            evidence = self._evidence(order, haystack)
            confidence = self._confidence(evidence)
            state = (
                MatchState.CONFIRMED_MATCH
                if "order_id" in evidence and len(evidence) >= 2
                else MatchState.LIKELY_MATCH
                if len(evidence) >= 2
                else MatchState.POSSIBLE_MATCH
            )
            candidates.append(
                DocumentLinkCandidate(
                    path=str(raw.get("path") or ""),
                    name=name,
                    location=str(raw.get("location") or ""),
                    state=state,
                    confidence=confidence,
                    evidence=evidence,
                    snippet=snippet,
                )
            )
        candidates.sort(
            key=lambda item: (
                item.state is MatchState.CONFIRMED_MATCH,
                item.state is MatchState.LIKELY_MATCH,
                item.confidence,
                item.path,
            ),
            reverse=True,
        )
        return tuple(candidates)

    @staticmethod
    def _query(order: OrderRecord) -> str:
        parts: list[str] = []
        order_id = _string_value(order.order_id)
        seller = _string_value(order.seller)
        amount = _float_value(order.amount)
        purchase_date = _string_value(order.purchase_date)
        if order_id:
            parts.append(order_id)
        if seller:
            parts.append(seller)
        if amount is not None:
            parts.append(f"{amount:.2f}")
        if purchase_date:
            parts.append(purchase_date)
        return " ".join(parts)

    @staticmethod
    def _evidence(order: OrderRecord, haystack: str) -> tuple[str, ...]:
        output: list[str] = []
        order_id = _string_value(order.order_id)
        seller = _string_value(order.seller)
        amount = _float_value(order.amount)
        purchase_date = _string_value(order.purchase_date)
        if order_id and order_id.casefold() in haystack:
            output.append("order_id")
        if seller and seller.casefold() in haystack:
            output.append("merchant")
        if amount is not None:
            forms = (f"{amount:.2f}", f"{amount:.2f}".replace(".", ","))
            if any(form in haystack for form in forms):
                output.append("amount")
        if purchase_date and purchase_date.casefold() in haystack:
            output.append("date")
        return tuple(output)

    @staticmethod
    def _confidence(evidence: tuple[str, ...]) -> float:
        weights = {"order_id": 0.5, "merchant": 0.2, "amount": 0.2, "date": 0.1}
        return round(min(0.99, sum(weights.get(item, 0.0) for item in evidence)), 3)


@dataclass(frozen=True, slots=True)
class PickupPoint:
    name: str
    raw_address: str
    normalized_address: str
    opening_hours: EvidenceValue
    provenance: tuple[ProvenanceRef, ...]


def normalize_pickup_point(
    name: str,
    address: str,
    *,
    provenance: ProvenanceRef,
    opening_hours: str | None = None,
) -> PickupPoint:
    clean_name = " ".join(str(name).split()).strip()[:200]
    raw_address = str(address).strip()[:500]
    normalized = " ".join(raw_address.split())
    hours = (
        EvidenceValue(opening_hours.strip(), 0.8, (provenance,))
        if opening_hours and opening_hours.strip()
        else EvidenceValue.unknown()
    )
    return PickupPoint(clean_name, raw_address, normalized, hours, (provenance,))


@dataclass(frozen=True, slots=True)
class PickupDeadline:
    due_at: float | None
    source_wording: str
    provenance: tuple[ProvenanceRef, ...]
    certain: bool


def calculate_pickup_deadline(
    *,
    arrival_at: float,
    source_wording: str,
    provenance: ProvenanceRef,
) -> PickupDeadline:
    wording = " ".join(str(source_wording).split()).strip()[:500]
    explicit = _EXPLICIT_DATE_RE.search(wording)
    if explicit is not None:
        try:
            due = datetime.fromisoformat(explicit.group(1)).replace(
                hour=23,
                minute=59,
                second=59,
                tzinfo=_PARIS,
            )
        except ValueError:
            return PickupDeadline(None, wording, (provenance,), False)
        return PickupDeadline(due.timestamp(), wording, (provenance,), True)

    duration = _PICKUP_DURATION_RE.search(wording)
    if duration is None:
        return PickupDeadline(None, wording, (provenance,), False)
    days = int(duration.group(1))
    if not 1 <= days <= 30:
        return PickupDeadline(None, wording, (provenance,), False)
    arrival = datetime.fromtimestamp(float(arrival_at), _PARIS)
    due = arrival + timedelta(days=days)
    return PickupDeadline(due.timestamp(), wording, (provenance,), True)


@dataclass(frozen=True, slots=True)
class SensitivePickupCode:
    available: bool
    value: str | None
    expires_at: float | None
    provenance: tuple[ProvenanceRef, ...]


def extract_pickup_code(message: EmailMessage) -> SensitivePickupCode:
    match = _CODE_RE.search(message.body)
    if match is None:
        return SensitivePickupCode(False, None, None, ())
    value = match.group(1).strip()
    expires_at = message.received_at + 10 * 86_400
    return SensitivePickupCode(True, value, expires_at, (message.provenance,))


@dataclass(frozen=True, slots=True)
class QRSource:
    available: bool
    reference: str | None
    generated: bool
    provenance: tuple[ProvenanceRef, ...]


def extract_qr_source(message: EmailMessage) -> QRSource:
    match = _QR_URL_RE.search(message.body)
    if match is None:
        return QRSource(False, None, False, ())
    reference = match.group(1).rstrip(".,;)")[:2000]
    return QRSource(True, reference, False, (message.provenance,))


@dataclass(frozen=True, slots=True)
class PickupParseResult:
    event: NormalizedEvent | None
    shipment: ShipmentRecord | None
    point: PickupPoint | None
    deadline: PickupDeadline | None
    code: SensitivePickupCode
    qr: QRSource
    confidence: float
    uncertain: bool
    reasons: tuple[str, ...] = ()


class MondialRelayParser:
    SOURCE_VERSION = "mondial-relay-email-v1"

    def parse(self, message: EmailMessage) -> PickupParseResult:
        trust = assess_email_trust(message)
        signal_kinds = tuple(item.kind for item in trust.signals)
        blocking = {"brand_domain_mismatch", "suspicious_link"}
        if blocking.intersection(signal_kinds):
            return self._uncertain(signal_kinds)

        text = f"{message.subject}\n{message.body}"
        lower = text.casefold()
        tracking_match = _TRACKING_RE.search(text)
        tracking = tracking_match.group(0).upper() if tracking_match is not None else ""
        pickup_ready = "disponible" in lower and (
            "point relais" in lower or "relais" in lower
        )
        if not pickup_ready or not tracking:
            return self._uncertain(("missing_pickup_evidence",))

        point = self._extract_point(message)
        deadline_wording = self._deadline_wording(message.body)
        deadline = calculate_pickup_deadline(
            arrival_at=message.received_at,
            source_wording=deadline_wording,
            provenance=message.provenance,
        )
        code = extract_pickup_code(message)
        qr = extract_qr_source(message)
        event = NormalizedEvent(
            source="mondial_relay_email",
            source_event_id=message.message_id,
            event_type="pickup_ready",
            occurred_at=message.received_at,
            observed_at=message.received_at,
            subject_refs=(f"tracking:{tracking}",),
            payload_summary=f"Colis disponible en Point Relais · {tracking}",
            provenance=(message.provenance,),
            confidence=0.96,
            source_version=self.SOURCE_VERSION,
        )
        shipment = ShipmentRecord(
            tracking_id=EvidenceValue(tracking, 0.99, (message.provenance,)),
            state=ShipmentState.PICKUP_READY,
            state_at=message.received_at,
            carrier=EvidenceValue("Mondial Relay", 0.98, (message.provenance,)),
            pickup_location=(
                EvidenceValue(point.normalized_address, 0.9, point.provenance)
                if point is not None
                else EvidenceValue.unknown()
            ),
            pickup_deadline=(
                EvidenceValue(deadline.due_at, 0.9, deadline.provenance)
                if deadline.certain and deadline.due_at is not None
                else EvidenceValue.unknown()
            ),
        )
        return PickupParseResult(
            event,
            shipment,
            point,
            deadline,
            code,
            qr,
            0.96,
            False,
            signal_kinds,
        )

    @staticmethod
    def _uncertain(reasons: tuple[str, ...]) -> PickupParseResult:
        return PickupParseResult(
            None,
            None,
            None,
            None,
            SensitivePickupCode(False, None, None, ()),
            QRSource(False, None, False, ()),
            0.3,
            True,
            reasons,
        )

    @staticmethod
    def _extract_point(message: EmailMessage) -> PickupPoint | None:
        match = _POINT_RE.search(message.body)
        if match is None:
            return None
        raw = match.group(1).strip()
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) < 2:
            return normalize_pickup_point(
                parts[0] if parts else "Point Relais",
                "",
                provenance=message.provenance,
            )
        return normalize_pickup_point(
            parts[0],
            ", ".join(parts[1:]),
            provenance=message.provenance,
        )

    @staticmethod
    def _deadline_wording(body: str) -> str:
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            if _PICKUP_DURATION_RE.search(sentence) or _EXPLICIT_DATE_RE.search(sentence):
                return sentence.strip()
        return ""


@dataclass(frozen=True, slots=True)
class ParcelProjection:
    situation: Situation | None
    match_state: MatchState
    inserted_event: bool = False


class ParcelProjector:
    """Project pickup-ready evidence into the canonical SituationStore."""

    def __init__(self, store: SituationStore) -> None:
        self.store = store

    def project(self, parsed: PickupParseResult) -> ParcelProjection:
        event = parsed.event
        shipment = parsed.shipment
        if event is None or shipment is None:
            return ParcelProjection(None, MatchState.POSSIBLE_MATCH)
        inserted = self.store.ingest_event(event)
        tracking = _string_value(shipment.tracking_id)
        entities: list[EntityRef] = [
            EntityRef(EntityKind.SHIPMENT, tracking, provenance=event.provenance)
        ]
        if parsed.point is not None and parsed.point.normalized_address:
            point_id = f"{parsed.point.name}|{parsed.point.normalized_address}"
            entities.append(
                EntityRef(EntityKind.PICKUP_POINT, point_id, provenance=parsed.point.provenance)
            )
        keys = correlation_keys(event, entities=entities)
        situation = self.store.find_situation_by_keys(keys)
        if situation is None:
            situation = Situation.create(
                f"Retrait colis {tracking}",
                domain=SituationDomain.SHIPMENT,
                state="pickup_ready",
                confidence=event.confidence,
            )
        for entity in entities:
            self.store.save_entity(entity)
            if entity.entity_id not in situation.entity_ids:
                situation.entity_ids.append(entity.entity_id)
        situation.add_event(event)
        situation.action_state = ActionState.PICKUP
        situation.responsibility = Responsibility.FATHER_MUST_ACT
        situation.metadata["tracking_id"] = tracking
        situation.metadata["carrier"] = "Mondial Relay"
        situation.metadata["shipment_state"] = ShipmentState.PICKUP_READY.value
        if parsed.point is not None:
            situation.metadata["pickup_point_name"] = parsed.point.name
            situation.metadata["pickup_address"] = parsed.point.normalized_address
            situation.metadata["pickup_address_raw"] = parsed.point.raw_address
        if parsed.deadline is not None and parsed.deadline.due_at is not None:
            situation.metadata["pickup_deadline"] = parsed.deadline.due_at
            situation.metadata["deadline_at"] = parsed.deadline.due_at
            situation.metadata["pickup_deadline_wording"] = parsed.deadline.source_wording
        if parsed.code.available:
            situation.metadata["pickup_code"] = parsed.code.value
            situation.metadata["pickup_code_expires_at"] = parsed.code.expires_at
            situation.metadata["pickup_code_source_id"] = message_source_id(parsed.code.provenance)
        if parsed.qr.available:
            situation.metadata["pickup_qr_reference"] = parsed.qr.reference
        self.store.save_situation(situation, correlation_keys=keys)
        self.store.mark_event_processed(event.identity_key)
        return ParcelProjection(situation, MatchState.CONFIRMED_MATCH, inserted)


def message_source_id(provenance: tuple[ProvenanceRef, ...]) -> str:
    return provenance[0].source_id if provenance else ""


def _string_value(value: EvidenceValue) -> str:
    return str(value.value).strip() if value.value is not None else ""


def _float_value(value: EvidenceValue) -> float | None:
    if value.value is None:
        return None
    try:
        return float(value.value)
    except (TypeError, ValueError):
        return None
