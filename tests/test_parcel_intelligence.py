from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis_papa.commerce_intelligence import EvidenceValue, OrderRecord, OrderState
from jarvis_papa.document_rag import DocumentHit
from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    MatchState,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationDomain,
    SituationTask,
    TaskStatus,
)

_PARIS = ZoneInfo("Europe/Paris")
_BASE = datetime(2026, 9, 3, 10, 0, tzinfo=_PARIS)
_BASE_TS = _BASE.timestamp()
_ORDER_ID = "171-1234567-1234567"
_TRACKING_ID = "MR123456789FR"


class _FakeRAG:
    def __init__(self, hits: list[DocumentHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def search(self, query: str, *, limit: int = 6, refresh: bool = True) -> dict[str, object]:
        self.queries.append(query)
        return {
            "ok": True,
            "state": "success",
            "results": [hit.to_dict() for hit in self.hits[:limit]],
        }


def _provenance(source_id: str) -> ProvenanceRef:
    return ProvenanceRef("email", source_id, _BASE_TS)


def _order() -> OrderRecord:
    evidence = _provenance("amazon-order")
    return OrderRecord(
        order_id=EvidenceValue(_ORDER_ID, 0.99, (evidence,)),
        state=OrderState.DELIVERED,
        state_at=_BASE_TS,
        purchase_date=EvidenceValue("2026-09-02", 0.96, (evidence,)),
        amount=EvidenceValue(49.99, 0.96, (evidence,)),
        seller=EvidenceValue("Amazon EU S.a.r.L.", 0.9, (evidence,)),
    )


def _message(
    message_id: str,
    body: str,
    *,
    subject: str = "Votre colis est disponible en Point Relais",
    sender: str = "Mondial Relay <suivi@mondialrelay.fr>",
) -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=_BASE_TS,
    )


def _pickup_message(message_id: str = "<pickup-1@example>") -> EmailMessage:
    return _message(
        message_id,
        (
            f"Votre colis {_TRACKING_ID} est disponible dans votre Point Relais. "
            "Point Relais : TABAC DU CENTRE, 12 rue de la Paix, 06000 Nice. "
            "Votre colis restera disponible pendant 7 jours. "
            "Code de retrait : 654321."
        ),
    )


def test_p4_08_matching_bank_refund_evidence_completes_pending_follow_up() -> None:
    from jarvis_papa.parcel_intelligence import RefundExpectation, RefundState, confirm_refund

    source = _provenance("refund-announcement")
    bank_source = ProvenanceRef("bank_fixture", "refund-credit", _BASE_TS + 86_400)
    expectation = RefundExpectation(
        amount=EvidenceValue(49.99, 0.96, (source,)),
        expected_by=EvidenceValue("2026-09-10", 0.9, (source,)),
        state=RefundState.REFUND_PENDING,
        provenance=(source,),
    )
    situation = Situation.create(
        "Remboursement commande",
        domain=SituationDomain.REFUND,
        state="pending",
        confidence=0.9,
    )
    situation.add_task(
        SituationTask.create(
            "Vérifier le remboursement",
            action_state=ActionState.FOLLOW_UP,
            responsibility=Responsibility.FATHER_MUST_ACT,
        )
    )

    result = confirm_refund(
        situation,
        expectation,
        credited_amount=49.99,
        observed_at=_BASE_TS + 86_400,
        provenance=bank_source,
    )

    assert result.matched is True
    assert result.state is RefundState.REFUNDED
    assert result.expected_amount == pytest.approx(49.99)
    assert result.expected_by == "2026-09-10"
    assert source in result.provenance
    assert bank_source in result.provenance
    assert situation.tasks[0].status is TaskStatus.COMPLETED
    assert situation.responsibility is Responsibility.COMPLETED


def test_p4_09_document_rag_links_strong_invoice_but_amount_only_stays_weak() -> None:
    from jarvis_papa.parcel_intelligence import OrderDocumentLinker

    hits = [
        DocumentHit(
            path="/docs/facture-amazon.pdf",
            name="facture-amazon.pdf",
            location="page 1",
            snippet=(
                f"Facture Amazon EU S.a.r.L. commande {_ORDER_ID} du 2026-09-02 total 49,99 €"
            ),
            score=0.95,
            modified_at=_BASE_TS,
            extractor="pdf",
        ),
        DocumentHit(
            path="/docs/autre-ticket.pdf",
            name="autre-ticket.pdf",
            location="page 1",
            snippet="Total payé 49,99 €",
            score=0.8,
            modified_at=_BASE_TS,
            extractor="pdf",
        ),
    ]
    rag = _FakeRAG(hits)
    linker = OrderDocumentLinker(rag)

    candidates = linker.find_candidates(_order())

    assert rag.queries
    assert _ORDER_ID in rag.queries[0]
    assert candidates[0].path.endswith("facture-amazon.pdf")
    assert candidates[0].state is MatchState.CONFIRMED_MATCH
    assert "order_id" in candidates[0].evidence
    assert "merchant" in candidates[0].evidence
    assert "amount" in candidates[0].evidence
    assert candidates[1].state is MatchState.POSSIBLE_MATCH
    assert candidates[1].evidence == ("amount",)
    assert candidates[1].confidence < 0.55


def test_p4_10_mondial_relay_pickup_ready_is_idempotently_projected(tmp_path: Path) -> None:
    from jarvis_papa.parcel_intelligence import MondialRelayParser, ParcelProjector

    parser = MondialRelayParser()
    parsed = parser.parse(_pickup_message())

    assert parsed.uncertain is False
    assert parsed.event is not None
    assert parsed.event.event_type == "pickup_ready"
    assert f"tracking:{_TRACKING_ID}" in parsed.event.subject_refs
    assert parsed.event.provenance == (_pickup_message().provenance,)
    assert parsed.shipment is not None
    assert parsed.shipment.state.value == "pickup_ready"

    store = SituationStore(tmp_path / "pickup.sqlite3")
    projector = ParcelProjector(store)
    first = projector.project(parsed)
    second = projector.project(parsed)

    assert first.situation is not None
    assert second.situation is not None
    assert first.situation.situation_id == second.situation.situation_id
    assert first.situation.domain is SituationDomain.SHIPMENT
    assert first.situation.action_state is ActionState.PICKUP
    assert len(store.list_situations()) == 1
    assert len(first.situation.event_ids) == 1


def test_p4_11_pickup_point_preserves_raw_address_and_does_not_invent_hours() -> None:
    from jarvis_papa.parcel_intelligence import normalize_pickup_point

    point = normalize_pickup_point(
        "TABAC DU CENTRE",
        " 12  rue de la Paix, 06000   Nice ",
        provenance=_provenance("pickup-point"),
    )

    assert point.name == "TABAC DU CENTRE"
    assert point.raw_address == "12  rue de la Paix, 06000   Nice"
    assert point.normalized_address == "12 rue de la Paix, 06000 Nice"
    assert point.opening_hours.value is None
    assert point.provenance == (_provenance("pickup-point"),)


def test_p4_12_explicit_seven_day_pickup_rule_resolves_in_europe_paris() -> None:
    from jarvis_papa.parcel_intelligence import calculate_pickup_deadline

    deadline = calculate_pickup_deadline(
        arrival_at=_BASE_TS,
        source_wording="Votre colis restera disponible pendant 7 jours.",
        provenance=_provenance("pickup-deadline"),
    )

    assert deadline.certain is True
    assert deadline.source_wording == "Votre colis restera disponible pendant 7 jours."
    assert deadline.due_at == pytest.approx((_BASE + timedelta(days=7)).timestamp())
    assert datetime.fromtimestamp(deadline.due_at, _PARIS).hour == 10

    ambiguous = calculate_pickup_deadline(
        arrival_at=_BASE_TS,
        source_wording="Votre colis restera disponible quelques jours.",
        provenance=_provenance("pickup-ambiguous"),
    )
    assert ambiguous.certain is False
    assert ambiguous.due_at is None


def test_p4_13_pickup_code_requires_explicit_label_and_has_short_expiry() -> None:
    from jarvis_papa.parcel_intelligence import extract_pickup_code

    message = _pickup_message()
    code = extract_pickup_code(message)
    assert code.available is True
    assert code.value == "654321"
    assert code.provenance == (message.provenance,)
    assert code.expires_at is not None
    assert code.expires_at - message.received_at <= 14 * 86_400

    ambiguous = _message(
        "<ambiguous-code@example>",
        f"Colis {_TRACKING_ID}. Référence dossier 654321. Présentez votre pièce d'identité.",
    )
    absent = extract_pickup_code(ambiguous)
    assert absent.available is False
    assert absent.value is None


def test_p4_14_qr_source_is_real_reference_or_explicitly_unavailable() -> None:
    from jarvis_papa.parcel_intelligence import extract_qr_source

    absent_message = _pickup_message()
    absent = extract_qr_source(absent_message)
    assert absent.available is False
    assert absent.reference is None
    assert absent.generated is False

    real_message = _message(
        "<pickup-qr@example>",
        (
            f"Votre colis {_TRACKING_ID} est disponible. "
            "QR de retrait : https://www.mondialrelay.fr/qr/fixture-abc123"
        ),
    )
    real = extract_qr_source(real_message)
    assert real.available is True
    assert real.reference == "https://www.mondialrelay.fr/qr/fixture-abc123"
    assert real.generated is False
    assert real.provenance == (real_message.provenance,)
