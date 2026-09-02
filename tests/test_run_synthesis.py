from __future__ import annotations

from pathlib import Path

from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    NormalizedEvent,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationDomain,
    SourceConnectionState,
    SourceHealth,
)


def _persisted_store(tmp_path: Path) -> SituationStore:
    store = SituationStore(tmp_path / "situations.sqlite3")

    parcel = Situation.create(
        "Colis Amazon à retirer",
        domain=SituationDomain.SHIPMENT,
        state="pickup_ready",
        confidence=0.96,
    )
    parcel.action_state = ActionState.PICKUP
    parcel.responsibility = Responsibility.FATHER_MUST_ACT
    parcel.metadata["pickup_expiring"] = True
    parcel_event = NormalizedEvent(
        source="amazon",
        source_event_id="amazon-pickup-1",
        event_type="pickup_ready",
        occurred_at=1_788_389_200.0,
        observed_at=1_788_389_260.0,
        payload_summary="Le colis Amazon est disponible au point relais jusqu'à demain.",
        provenance=(
            ProvenanceRef(
                "amazon",
                "amazon-pickup-1",
                1_788_389_260.0,
                locator="orders/123",
            ),
        ),
        confidence=0.99,
    )
    parcel.add_event(parcel_event)
    store.save_situation(parcel, correlation_keys=("amazon:123",))

    refund = Situation.create(
        "Remboursement marchand",
        domain=SituationDomain.REFUND,
        state="pending",
        confidence=0.9,
    )
    refund.action_state = ActionState.READ_ONLY
    refund.responsibility = Responsibility.OTHER_PARTY_MUST_ACT
    refund_event = NormalizedEvent(
        source="mail",
        source_event_id="refund-mail-1",
        event_type="refund_pending",
        occurred_at=1_788_388_000.0,
        observed_at=1_788_388_100.0,
        payload_summary="Le marchand annonce un remboursement sous cinq jours.",
        confidence=0.95,
    )
    refund.add_event(refund_event)
    store.save_situation(refund, correlation_keys=("refund:merchant:1",))
    return store


def test_p3_15_final_synthesis_uses_only_persisted_discoveries(tmp_path: Path) -> None:
    from jarvis_papa.run_synthesis import RunSynthesizer

    store = _persisted_store(tmp_path)
    synthesis = RunSynthesizer(store).build(
        source_health=(
            SourceHealth("amazon", SourceConnectionState.CONNECTED, 1_788_389_300.0),
            SourceHealth("mail", SourceConnectionState.CONNECTED, 1_788_389_300.0),
        )
    )

    assert synthesis.processed_events == 2
    assert synthesis.important_situations == ("Colis Amazon à retirer",)
    assert synthesis.decisions_for_robert == ("Colis Amazon à retirer",)
    assert synthesis.degraded_sources == ()
    assert "Colis Amazon à retirer" in synthesis.text
    assert "Remboursement marchand" in synthesis.text
    lowered = synthesis.text.casefold()
    assert "j'ai vérifié" not in lowered
    assert "j’ai vérifié" not in lowered
    assert "tout vérifié" not in lowered


def test_p3_16_source_failure_is_plain_french_but_keeps_technical_diagnostic() -> None:
    from jarvis_papa.run_synthesis import humanize_source_failure

    presentation = humanize_source_failure(
        "Amazon",
        "HTTP 500 from http://127.0.0.1:8000/orders; RuntimeError: connector unavailable",
    )

    visible = presentation.user_message.casefold()
    assert "amazon" in visible
    assert "je continue avec" in visible
    assert "http" not in visible
    assert "500" not in visible
    assert "127.0.0.1" not in visible
    assert "runtimeerror" not in visible
    assert presentation.technical_detail.startswith("HTTP 500")


def test_p3_17_offline_fact_is_last_known_with_observed_timestamp() -> None:
    from jarvis_papa.run_synthesis import FreshnessState, render_external_fact

    provenance = ProvenanceRef(
        "amazon",
        "order-123",
        1_788_389_260.0,
        locator="orders/123",
    )
    offline = SourceHealth(
        "amazon",
        SourceConnectionState.DISCONNECTED,
        1_788_389_400.0,
        detail="network unavailable",
    )

    fact = render_external_fact(
        "Colis disponible au point relais",
        provenance=provenance,
        health=offline,
    )

    assert fact.observed_at == provenance.observed_at
    assert fact.freshness is FreshnessState.LAST_KNOWN
    assert "dernière information connue" in fact.display_text.casefold()
    assert "2026-09-02" in fact.display_text
    assert "actuel" not in fact.display_text.casefold()


def test_p3_17_connected_fact_is_current() -> None:
    from jarvis_papa.run_synthesis import FreshnessState, render_external_fact

    provenance = ProvenanceRef("mail", "message-1", 1_788_389_260.0)
    health = SourceHealth("mail", SourceConnectionState.CONNECTED, 1_788_389_300.0)

    fact = render_external_fact(
        "Le marchand attend notre réponse",
        provenance=provenance,
        health=health,
    )

    assert fact.freshness is FreshnessState.CURRENT
    assert "information actuelle" in fact.display_text.casefold()
