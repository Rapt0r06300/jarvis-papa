from __future__ import annotations

from pathlib import Path

import pytest

from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    MatchState,
    Responsibility,
    SituationDomain,
    SituationTask,
    TaskStatus,
)

_ORDER_ID = "171-1234567-1234567"
_TRACKING_ID = "MR123456789FR"
_BASE_TS = 1_788_393_600.0


def _message(
    message_id: str,
    subject: str,
    body: str,
    *,
    sender: str = "Amazon.fr <shipment-tracking@amazon.fr>",
    received_at: float = _BASE_TS,
) -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=received_at,
    )


def _order_message(message_id: str = "<order-1@example>") -> EmailMessage:
    return _message(
        message_id,
        f"Votre commande Amazon.fr {_ORDER_ID}",
        (
            f"Merci pour votre commande. Commande n° {_ORDER_ID}. "
            "Article : Aspirateur compact. Montant : 49,99 €. "
            "Vendeur : Amazon EU S.a.r.L. Date de commande : 2026-09-02."
        ),
    )


def _shipment_message(message_id: str = "<shipment-1@example>") -> EmailMessage:
    return _message(
        message_id,
        f"Votre commande {_ORDER_ID} a été expédiée",
        (
            f"Commande n° {_ORDER_ID}. Votre colis a été expédié. "
            f"Numéro de suivi : {_TRACKING_ID}. "
            "Livraison prévue : 2026-09-04."
        ),
        received_at=_BASE_TS + 3600,
    )


def _delay_message(message_id: str = "<delay-1@example>") -> EmailMessage:
    return _message(
        message_id,
        f"Retard de livraison pour la commande {_ORDER_ID}",
        (
            f"Commande n° {_ORDER_ID}. Le colis {_TRACKING_ID} est retardé. "
            "Nouvelle livraison prévue : 2026-09-04."
        ),
        received_at=_BASE_TS + 7200,
    )


def _delivered_message(
    message_id: str = "<delivered-1@example>",
    *,
    sender: str = "Amazon.fr <shipment-tracking@amazon.fr>",
) -> EmailMessage:
    return _message(
        message_id,
        f"Votre colis pour la commande {_ORDER_ID} a été livré",
        f"Commande n° {_ORDER_ID}. Le colis {_TRACKING_ID} a été livré.",
        sender=sender,
        received_at=_BASE_TS + 10_800,
    )


def test_p4_01_order_model_is_typed_source_agnostic_and_provenance_aware() -> None:
    from jarvis_papa.commerce_intelligence import EvidenceValue, OrderRecord, OrderState
    from jarvis_papa.situations import ProvenanceRef

    evidence = ProvenanceRef("email", "order-evidence", _BASE_TS)
    order = OrderRecord(
        order_id=EvidenceValue(_ORDER_ID, 0.99, (evidence,)),
        state=OrderState.ORDERED,
        state_at=_BASE_TS,
        purchase_date=EvidenceValue("2026-09-02", 0.96, (evidence,)),
        items=EvidenceValue(("Aspirateur compact",), 0.9, (evidence,)),
        amount=EvidenceValue(49.99, 0.96, (evidence,)),
        seller=EvidenceValue("Boutique exemple", 0.88, (evidence,)),
    )

    assert order.state is OrderState.ORDERED
    assert order.order_id.value == _ORDER_ID
    assert order.amount.value == pytest.approx(49.99)
    assert order.seller.provenance == (evidence,)
    assert order.order_id.confidence == pytest.approx(0.99)

    order = order.transitioned(OrderState.PREPARING, at=_BASE_TS + 10)
    order = order.transitioned(OrderState.SHIPPED, at=_BASE_TS + 20)
    order = order.transitioned(OrderState.IN_TRANSIT, at=_BASE_TS + 30)
    order = order.transitioned(OrderState.DELAYED, at=_BASE_TS + 40)
    order = order.transitioned(OrderState.DELIVERED, at=_BASE_TS + 50)
    assert order.state is OrderState.DELIVERED
    with pytest.raises(ValueError):
        order.transitioned(OrderState.SHIPPED, at=_BASE_TS + 60)


def test_p4_02_shipment_can_exist_independently_and_rejects_stale_backwards_state() -> None:
    from jarvis_papa.commerce_intelligence import EvidenceValue, ShipmentRecord, ShipmentState
    from jarvis_papa.situations import ProvenanceRef

    evidence = ProvenanceRef("email", "shipment-evidence", _BASE_TS)
    shipment = ShipmentRecord(
        tracking_id=EvidenceValue(_TRACKING_ID, 0.98, (evidence,)),
        state=ShipmentState.IN_TRANSIT,
        state_at=_BASE_TS + 20,
        carrier=EvidenceValue("Mondial Relay", 0.8, (evidence,)),
        order_id=EvidenceValue(None, 0.0, ()),
    )
    assert shipment.order_id.value is None
    assert shipment.tracking_id.provenance == (evidence,)

    delayed = shipment.transitioned(ShipmentState.DELAYED, at=_BASE_TS + 30)
    assert delayed.state is ShipmentState.DELAYED
    with pytest.raises(ValueError):
        delayed.transitioned(ShipmentState.IN_TRANSIT, at=_BASE_TS + 10)


def test_p4_03_amazon_parser_emits_normalized_event_and_rejects_spoofed_brand() -> None:
    from jarvis_papa.commerce_intelligence import AmazonCommerceParser, OrderState

    parser = AmazonCommerceParser()
    genuine = parser.parse(_order_message())
    assert genuine.uncertain is False
    assert genuine.event is not None
    assert genuine.event.event_type == "order_confirmed"
    assert f"order:{_ORDER_ID}" in genuine.event.subject_refs
    assert genuine.event.provenance == (_order_message().provenance,)
    assert genuine.order is not None
    assert genuine.order.state is OrderState.ORDERED
    assert genuine.order.order_id.value == _ORDER_ID
    assert genuine.order.items.value == ("Aspirateur compact",)
    assert genuine.order.amount.value == pytest.approx(49.99)
    assert genuine.order.seller.value == "Amazon EU S.a.r.L."

    spoofed = parser.parse(
        _message(
            "<spoof-1@example>",
            f"Amazon : commande {_ORDER_ID} confirmée",
            f"Commande n° {_ORDER_ID}. Montant : 999,99 €. Cliquez immédiatement.",
            sender="Amazon <alerts@amaz0n-security.example>",
        )
    )
    assert spoofed.uncertain is True
    assert spoofed.event is None
    assert spoofed.order is None
    assert spoofed.confidence < 0.5
    assert "brand_domain_mismatch" in spoofed.reasons


def test_p4_04_repeated_order_confirmation_is_idempotent_and_missing_stays_unknown(
    tmp_path: Path,
) -> None:
    from jarvis_papa.commerce_intelligence import AmazonCommerceParser, CommerceProjector

    store = SituationStore(tmp_path / "commerce.sqlite3")
    parser = AmazonCommerceParser()
    projector = CommerceProjector(store)
    message = _message(
        "<order-minimal@example>",
        f"Commande Amazon.fr {_ORDER_ID}",
        f"Merci. Commande n° {_ORDER_ID}. Date de commande : 2026-09-02.",
    )
    parsed = parser.parse(message)
    assert parsed.order is not None
    assert parsed.order.amount.value is None
    assert parsed.order.seller.value is None

    first = projector.project(parsed)
    second = projector.project(parsed)
    assert first.situation is not None
    assert second.situation is not None
    assert first.situation.situation_id == second.situation.situation_id
    stored = store.list_situations()
    assert len(stored) == 1
    assert len(stored[0].event_ids) == 1
    assert stored[0].domain is SituationDomain.ORDER


def test_p4_05_strong_order_id_merges_shipment_and_weak_link_stays_possible(
    tmp_path: Path,
) -> None:
    from jarvis_papa.commerce_intelligence import (
        AmazonCommerceParser,
        CommerceProjector,
        EvidenceValue,
        ShipmentRecord,
        ShipmentState,
        match_order_shipment,
    )

    store = SituationStore(tmp_path / "commerce.sqlite3")
    parser = AmazonCommerceParser()
    projector = CommerceProjector(store)
    order_result = parser.parse(_order_message())
    shipment_result = parser.parse(_shipment_message())
    projected_order = projector.project(order_result)
    projected_shipment = projector.project(shipment_result)

    assert projected_order.situation is not None
    assert projected_shipment.situation is not None
    assert projected_order.situation.situation_id == projected_shipment.situation.situation_id
    stored = store.list_situations()
    assert len(stored) == 1
    assert len(stored[0].event_ids) == 2
    assert stored[0].metadata["tracking_id"] == _TRACKING_ID
    assert projected_shipment.match_state is MatchState.CONFIRMED_MATCH

    assert order_result.order is not None
    weak = ShipmentRecord(
        tracking_id=EvidenceValue("WEAK-TRACKING", 0.6, ()),
        state=ShipmentState.IN_TRANSIT,
        state_at=_BASE_TS,
        order_id=EvidenceValue(None, 0.0, ()),
    )
    match = match_order_shipment(order_result.order, weak)
    assert match.state in {MatchState.POSSIBLE_MATCH, MatchState.LIKELY_MATCH}
    assert match.state is not MatchState.CONFIRMED_MATCH


def test_p4_06_explicit_one_day_delay_is_evidence_backed_and_prioritized(
    tmp_path: Path,
) -> None:
    from jarvis_papa.commerce_intelligence import AmazonCommerceParser, CommerceProjector

    store = SituationStore(tmp_path / "commerce.sqlite3")
    parser = AmazonCommerceParser()
    projector = CommerceProjector(store)
    projector.project(parser.parse(_order_message()))
    projector.project(parser.parse(_shipment_message()))
    delayed = projector.project(parser.parse(_delay_message()), now=_BASE_TS + 7200)

    assert delayed.situation is not None
    assert delayed.situation.metadata["shipment_state"] == "delayed"
    assert delayed.situation.metadata["delay_evidence"] == "explicit_source"
    assert delayed.situation.action_state is ActionState.VERIFY
    assert delayed.priority is not None
    assert delayed.priority.band in {"A_SURVEILLER", "A_FAIRE"}
    assert any("deadline" in item for item in delayed.priority.contributions)


def test_p4_07_verified_delivery_closes_tasks_but_spoofed_delivery_does_not(
    tmp_path: Path,
) -> None:
    from jarvis_papa.commerce_intelligence import AmazonCommerceParser, CommerceProjector

    store = SituationStore(tmp_path / "commerce.sqlite3")
    parser = AmazonCommerceParser()
    projector = CommerceProjector(store)
    order_projection = projector.project(parser.parse(_order_message()))
    projector.project(parser.parse(_shipment_message()))
    assert order_projection.situation is not None

    situation = store.get_situation(order_projection.situation.situation_id)
    assert situation is not None
    situation.add_task(
        SituationTask.create(
            "Vérifier la livraison du colis",
            action_state=ActionState.FOLLOW_UP,
            responsibility=Responsibility.FATHER_MUST_ACT,
        )
    )
    store.save_situation(situation, correlation_keys=(f"order:{_ORDER_ID}",))

    spoofed = parser.parse(
        _delivered_message(
            "<fake-delivery@example>",
            sender="Amazon <delivery@amaz0n-security.example>",
        )
    )
    assert spoofed.event is None
    projector.project(spoofed)
    unchanged = store.get_situation(situation.situation_id)
    assert unchanged is not None
    assert unchanged.tasks[0].status is TaskStatus.OPEN

    delivered = projector.project(parser.parse(_delivered_message()))
    assert delivered.situation is not None
    assert delivered.situation.tasks[0].status is TaskStatus.COMPLETED
    assert delivered.situation.action_state is ActionState.NO_ACTION
    assert delivered.situation.responsibility is Responsibility.COMPLETED
