from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis_papa.commerce_intelligence import (
    AmazonCommerceParser,
    CommerceProjector,
    EvidenceValue,
    OrderRecord,
    OrderState,
    ShipmentRecord,
    ShipmentState,
)
from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    MatchState,
    NormalizedEvent,
    ProvenanceRef,
    Situation,
    SituationDomain,
)

_PARIS = ZoneInfo("Europe/Paris")
_BASE = datetime(2026, 9, 3, 10, 0, tzinfo=_PARIS)
_BASE_TS = _BASE.timestamp()
_ORDER_ID = "171-7654321-1234567"
_TRACKING = "MR987654321FR"


def _prov(source: str, source_id: str, at: float = _BASE_TS) -> ProvenanceRef:
    return ProvenanceRef(source, source_id, at)


def _amazon_shipment() -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id="<amazon-shipment-p4c@example.test>",
        sender="Amazon <shipment-tracking@amazon.fr>",
        subject="Votre commande Amazon a été expédiée",
        body=(
            f"Commande {_ORDER_ID}. Votre colis {_TRACKING} a été expédié. "
            "Livraison prévue : 2026-09-05."
        ),
        received_at=_BASE_TS,
    )


def _mondial_pickup() -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id="<mondial-pickup-p4c@example.test>",
        sender="Mondial Relay <suivi@mondialrelay.fr>",
        subject="Votre colis est disponible en Point Relais",
        body=(
            f"Votre colis {_TRACKING} est disponible dans votre Point Relais. "
            "Point Relais : RELAIS FIXTURE, 10 rue Exemple, 00000 Testville. "
            "Votre colis restera disponible pendant 7 jours. Code de retrait : 246810."
        ),
        received_at=_BASE_TS + 86_400,
    )


def test_p4_15_tracking_normalization_is_stable_and_preserves_raw_carrier_source() -> None:
    from jarvis_papa.parcel_intelligence import (
        merge_tracking_references,
        normalize_tracking_reference,
    )

    source = _prov("carrier_fixture", "tracking-a")
    first = normalize_tracking_reference(
        "  MR 987-654-321 FR  ",
        carrier="Mondial Relay",
        provenance=source,
    )
    second = normalize_tracking_reference(
        "mr987654321fr",
        carrier="Mondial Relay",
        provenance=source,
    )

    assert first.normalized == _TRACKING
    assert second.normalized == _TRACKING
    assert first.raw == "MR 987-654-321 FR"
    assert first.carrier == "Mondial Relay"
    assert first.provenance == (source,)

    mismatch = normalize_tracking_reference(
        "MR 987-654-321 FR",
        carrier="UPS",
        provenance=_prov("carrier_fixture", "tracking-b"),
    )
    merged = merge_tracking_references(first, mismatch)
    assert merged.conflict is True
    assert merged.reference.raw == first.raw
    assert merged.reference.carrier == first.carrier


def test_p4_16_amazon_and_carrier_same_tracking_converge_on_one_situation(tmp_path: Path) -> None:
    from jarvis_papa.parcel_intelligence import build_carrier_tracking_update

    store = SituationStore(tmp_path / "p4c-carrier.sqlite3")
    projector = CommerceProjector(store)
    amazon = AmazonCommerceParser().parse(_amazon_shipment())
    amazon_projection = projector.project(amazon, now=_BASE_TS)
    assert amazon_projection.situation is not None

    carrier = build_carrier_tracking_update(
        raw_tracking="MR 987 654 321 FR",
        carrier="Mondial Relay",
        state=ShipmentState.IN_TRANSIT,
        source="carrier_fixture",
        source_event_id="carrier-event-1",
        occurred_at=_BASE_TS + 3_600,
        observed_at=_BASE_TS + 3_600,
        provenance=_prov("carrier_fixture", "carrier-event-1", _BASE_TS + 3_600),
    )
    carrier_projection = projector.project(carrier, now=_BASE_TS + 3_600)

    assert carrier_projection.situation is not None
    assert carrier_projection.situation.situation_id == amazon_projection.situation.situation_id
    assert carrier_projection.match_state is MatchState.CONFIRMED_MATCH
    assert len(store.list_situations()) == 1

    date_only_order = OrderRecord(
        order_id=EvidenceValue.unknown(),
        state=OrderState.SHIPPED,
        state_at=_BASE_TS,
        purchase_date=EvidenceValue("2026-09-03", 0.7, (_prov("fixture", "date-order"),)),
    )
    date_only_shipment = ShipmentRecord(
        tracking_id=EvidenceValue.unknown(),
        state=ShipmentState.IN_TRANSIT,
        state_at=_BASE_TS,
        expected_delivery=EvidenceValue("2026-09-03", 0.7, (_prov("fixture", "date-shipment"),)),
    )
    from jarvis_papa.parcel_intelligence import correlate_order_carrier

    weak = correlate_order_carrier(date_only_order, date_only_shipment)
    assert weak.state in {MatchState.POSSIBLE_MATCH, MatchState.LIKELY_MATCH}
    assert weak.state is not MatchState.CONFIRMED_MATCH


def test_p4_17_amazon_and_mondial_strong_tracking_yield_one_pickup_situation(tmp_path: Path) -> None:
    from jarvis_papa.parcel_intelligence import (
        MondialRelayParser,
        ParcelProjector,
        correlate_amazon_mondial,
    )

    store = SituationStore(tmp_path / "p4c-mondial.sqlite3")
    commerce_projector = CommerceProjector(store)
    amazon = AmazonCommerceParser().parse(_amazon_shipment())
    amazon_projection = commerce_projector.project(amazon, now=_BASE_TS)
    assert amazon_projection.situation is not None
    assert amazon.shipment is not None

    parsed_pickup = MondialRelayParser().parse(_mondial_pickup())
    assert parsed_pickup.shipment is not None
    correlation = correlate_amazon_mondial(amazon.shipment, parsed_pickup.shipment)
    assert correlation.state is MatchState.CONFIRMED_MATCH

    pickup_projection = ParcelProjector(store).project(parsed_pickup)
    assert pickup_projection.situation is not None
    assert pickup_projection.situation.situation_id == amazon_projection.situation.situation_id
    assert len(store.list_situations()) == 1


def test_p4_18_pickup_acknowledgement_suppresses_immediate_repeat_and_cadence_tightens() -> None:
    from jarvis_papa.parcel_intelligence import PickupReminderPolicy

    policy = PickupReminderPolicy()
    parcel_id = _TRACKING
    two_days = (_BASE + timedelta(days=2)).timestamp()

    assert policy.should_remind(parcel_id, deadline_at=two_days, now=_BASE_TS) is True
    policy.record_reminder(parcel_id, at=_BASE_TS)
    policy.acknowledge(parcel_id, at=_BASE_TS + 60)
    assert policy.should_remind(parcel_id, deadline_at=two_days, now=_BASE_TS + 5 * 60) is False

    far_interval = policy.cadence_seconds(deadline_at=(_BASE + timedelta(days=5)).timestamp(), now=_BASE_TS)
    near_interval = policy.cadence_seconds(deadline_at=(_BASE + timedelta(hours=6)).timestamp(), now=_BASE_TS)
    assert near_interval < far_interval

    policy.snooze(parcel_id, until=_BASE_TS + 4 * 3_600)
    assert policy.should_remind(parcel_id, deadline_at=two_days, now=_BASE_TS + 2 * 3_600) is False


def _order_situation(order_id: str, state: str, confidence: float, event_count: int) -> Situation:
    situation = Situation.create(
        f"Commande {order_id}",
        domain=SituationDomain.ORDER,
        state=state,
        confidence=confidence,
    )
    situation.metadata["order_id"] = order_id
    for index in range(event_count):
        event = NormalizedEvent(
            source="synthetic_mail",
            source_event_id=f"{order_id}-mail-{index}",
            event_type="order_update",
            occurred_at=_BASE_TS + index,
            observed_at=_BASE_TS + index,
            subject_refs=(f"order:{order_id}",),
            payload_summary=f"Mise à jour {index} pour {order_id}",
            provenance=(_prov("synthetic_mail", f"{order_id}-mail-{index}", _BASE_TS + index),),
            confidence=confidence,
            source_version="p4c-fixture-v1",
        )
        situation.add_event(event)
    return situation


def test_p4_19_order_briefing_projects_one_current_state_per_order_not_email() -> None:
    from jarvis_papa.parcel_intelligence import build_order_briefing

    situations = [
        _order_situation("ORDER-A", "delivered", 0.99, 4),
        _order_situation("ORDER-B", "pickup_ready", 0.96, 5),
        _order_situation("ORDER-C", "delayed", 0.92, 3),
        _order_situation("ORDER-D", "refund_pending", 0.88, 6),
    ]

    briefing = build_order_briefing(situations)

    assert len(briefing) == 4
    assert {item.order_id for item in briefing} == {"ORDER-A", "ORDER-B", "ORDER-C", "ORDER-D"}
    assert {item.state for item in briefing} == {
        "delivered",
        "pickup_ready",
        "delayed",
        "refund_pending",
    }
    assert all(item.timeline_events >= 3 for item in briefing)
    assert all(0.0 < item.confidence <= 1.0 for item in briefing)


def test_p4_20_synthetic_parcel_benchmark_covers_ground_truth_and_correct_priority() -> None:
    from jarvis_papa.parcel_intelligence import run_parcel_benchmark

    report = run_parcel_benchmark(now=_BASE_TS)

    assert report["synthetic_only"] is True
    assert report["contains_real_personal_data"] is False
    assert report["scenario_version"] == "parcel-e2e-v1"
    assert report["pickup_situations"] == 1
    assert report["correct_priority"] is True
    ground_truth = report["ground_truth"]
    assert isinstance(ground_truth, dict)
    assert set(ground_truth) >= {
        "correlation",
        "status",
        "deadline",
        "code_available",
        "qr_available",
        "tasks",
        "priority",
    }
    assert ground_truth["status"] == "pickup_ready"
    assert ground_truth["code_available"] is True
    assert ground_truth["qr_available"] is False
