from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis_papa.situations import ActionState, NormalizedEvent, ProvenanceRef

_BASE_TS = 1_788_431_200.0
_PARIS = ZoneInfo("Europe/Paris")


def _prov(source_id: str, observed_at: float = _BASE_TS) -> ProvenanceRef:
    return ProvenanceRef("marketplace_fixture", source_id, observed_at)


def _listing(*, observed_at: float = _BASE_TS):
    from jarvis_papa.marketplace_intelligence import (
        ListingStatus,
        MarketplaceListing,
        MarketplacePlatform,
        MarketplacePrice,
    )

    provenance = (_prov("listing-price", observed_at),)
    return MarketplaceListing(
        listing_id="lbc-987",
        platform=MarketplacePlatform.LEBONCOIN,
        title="Caméra X",
        price=MarketplacePrice(50.0, "EUR", 0.99, provenance),
        description="Très bon état",
        status=ListingStatus.ACTIVE,
        item_refs=("item:camera-x",),
        provenance=provenance,
    )


def test_p5_08_asking_price_is_verified_stale_or_unknown_without_guessing() -> None:
    from jarvis_papa.marketplace_intelligence import AskingPriceState, ground_asking_price

    current = ground_asking_price(
        _listing(),
        now=_BASE_TS + 60,
        max_age_seconds=300,
    )
    assert current.state is AskingPriceState.VERIFIED
    assert current.amount == 50.0
    assert current.currency == "EUR"
    assert current.provenance
    assert current.guessed is False

    stale = ground_asking_price(
        _listing(),
        now=_BASE_TS + 3_600,
        max_age_seconds=300,
    )
    assert stale.state is AskingPriceState.STALE
    assert stale.amount == 50.0
    assert "stale" in stale.reason.casefold() or "ancien" in stale.reason.casefold()
    assert stale.guessed is False

    missing = ground_asking_price(None, now=_BASE_TS + 60, max_age_seconds=300)
    assert missing.state is AskingPriceState.UNKNOWN
    assert missing.amount is None
    assert missing.currency is None
    assert missing.guessed is False


def test_p5_09_40_on_50_can_recommend_45_with_explicit_basis_and_never_transact() -> None:
    from jarvis_papa.marketplace_intelligence import (
        AskingPriceState,
        GroundedAskingPrice,
        NegotiationDecision,
        NegotiationOffer,
        NegotiationPolicy,
        recommend_negotiation,
    )

    offer_prov = _prov("offer")
    listing_prov = _prov("listing")
    asking = GroundedAskingPrice(
        amount=50.0,
        currency="EUR",
        state=AskingPriceState.VERIFIED,
        provenance=(listing_prov,),
        reason="Prix courant vérifié sur l'annonce.",
        guessed=False,
    )
    offer = NegotiationOffer(
        offered_amount=40.0,
        asking_amount=50.0,
        currency="EUR",
        conditions="",
        confidence=0.99,
        provenance=(offer_prov,),
    )

    recommendation = recommend_negotiation(
        offer,
        asking,
        NegotiationPolicy(counter_ratio=0.90, accept_ratio=0.95, refuse_below_ratio=0.60),
    )

    assert recommendation.decision is NegotiationDecision.COUNTER
    assert recommendation.proposed_amount == 45.0
    assert "50" in recommendation.basis
    assert "40" in recommendation.basis
    assert recommendation.executes_transaction is False
    assert recommendation.action_state is ActionState.USER_DECISION
    assert offer_prov in recommendation.provenance
    assert listing_prov in recommendation.provenance

    unknown = GroundedAskingPrice(
        amount=None,
        currency=None,
        state=AskingPriceState.UNKNOWN,
        provenance=(),
        reason="Prix inconnu.",
        guessed=False,
    )
    needs_price = recommend_negotiation(offer, unknown, NegotiationPolicy())
    assert needs_price.decision is NegotiationDecision.NEEDS_PRICE
    assert needs_price.proposed_amount is None
    assert needs_price.executes_transaction is False


def test_p5_10_grounded_offer_reply_uses_evidence_and_remains_unsent() -> None:
    from jarvis_papa.marketplace_intelligence import (
        AskingPriceState,
        GroundedAskingPrice,
        MarketplaceReplyDraft,
        NegotiationDecision,
        NegotiationRecommendation,
        draft_marketplace_reply,
    )

    provenance = (_prov("listing"), _prov("offer"))
    recommendation = NegotiationRecommendation(
        decision=NegotiationDecision.COUNTER,
        proposed_amount=45.0,
        currency="EUR",
        basis="Offre 40 € face au prix vérifié de 50 €; contre-proposition à 45 €.",
        action_state=ActionState.USER_DECISION,
        executes_transaction=False,
        provenance=provenance,
    )
    asking = GroundedAskingPrice(
        amount=50.0,
        currency="EUR",
        state=AskingPriceState.VERIFIED,
        provenance=(_prov("listing"),),
        reason="Prix courant vérifié sur l'annonce.",
        guessed=False,
    )

    draft = draft_marketplace_reply(
        listing=_listing(),
        asking_price=asking,
        recommendation=recommendation,
    )

    assert isinstance(draft, MarketplaceReplyDraft)
    assert "Caméra X" in draft.body
    assert "45" in draft.body
    assert draft.sent is False
    assert draft.action_state is ActionState.REPLY
    assert draft.provenance
    assert set(draft.grounded_facts) <= {"listing_title", "asking_price", "counter_price"}
    assert not hasattr(draft, "send")


def test_p5_11_style_learning_requires_repetition_and_can_be_inspected_corrected_and_forgotten() -> None:
    from jarvis_papa.marketplace_intelligence import MarketplaceStyleLearner

    learner = MarketplaceStyleLearner(min_observations=3)
    scope = "marketplace:seller-replies"

    learner.record_approved_reply(scope, "Bonjour, oui c'est disponible. Merci.", _prov("style-1"))
    first = learner.inspect(scope)
    assert first is not None
    assert first.observation_count == 1
    assert first.durable is False

    learner.record_approved_reply(scope, "Bonjour, 45 € me convient. Merci.", _prov("style-2"))
    learner.record_approved_reply(scope, "Bonjour, remise en main propre possible. Merci.", _prov("style-3"))
    learned = learner.inspect(scope)
    assert learned is not None
    assert learned.observation_count == 3
    assert learned.durable is True
    assert learned.concise_confidence > 0.0
    assert len(learned.provenance) == 3

    corrected = learner.correct(scope, concise=False)
    assert corrected is not None
    assert corrected.concise is False
    learner.forget(scope)
    assert learner.inspect(scope) is None


def test_p5_12_hand_delivery_intent_is_structured_provenanced_and_non_transactional() -> None:
    from jarvis_papa.marketplace_intelligence import DeliveryMode, extract_delivery_intent

    provenance = _prov("delivery")
    intent = extract_delivery_intent(
        "Je préfère une remise en mains propres demain.",
        provenance=provenance,
    )

    assert intent.mode is DeliveryMode.HANDOFF
    assert intent.provenance == (provenance,)
    assert intent.creates_transaction is False
    assert intent.action_state in {ActionState.REPLY, ActionState.USER_DECISION}


def test_p5_13_tomorrow_18h_is_normalized_but_ambiguous_time_requires_confirmation() -> None:
    from jarvis_papa.marketplace_intelligence import extract_appointment_proposal

    received = datetime(2026, 9, 3, 10, 0, tzinfo=_PARIS)
    provenance = _prov("appointment", received.timestamp())

    proposal = extract_appointment_proposal(
        "On peut se voir demain à 18h à Nice ?",
        message_timestamp=received.timestamp(),
        timezone_name="Europe/Paris",
        provenance=provenance,
    )
    expected = datetime(2026, 9, 4, 18, 0, tzinfo=_PARIS).timestamp()
    assert proposal.source_text == "demain à 18h"
    assert proposal.normalized_at == expected
    assert proposal.timezone_name == "Europe/Paris"
    assert proposal.location == "Nice"
    assert proposal.needs_confirmation is False
    assert proposal.action_state is ActionState.USER_DECISION
    assert proposal.provenance == (provenance,)

    ambiguous = extract_appointment_proposal(
        "On peut se voir demain en fin de journée ?",
        message_timestamp=received.timestamp(),
        timezone_name="Europe/Paris",
        provenance=provenance,
    )
    assert ambiguous.source_text
    assert ambiguous.normalized_at is None
    assert ambiguous.needs_confirmation is True
    assert ambiguous.location is None


def test_p5_14_paid_event_moves_to_shipping_required_without_financial_action() -> None:
    from jarvis_papa.marketplace_intelligence import (
        MarketplaceSaleLifecycle,
        SaleLifecycleState,
        apply_marketplace_event,
    )

    paid_provenance = _prov("paid-event")
    paid = NormalizedEvent(
        source="ebay_email",
        source_event_id="payment-123",
        event_type="marketplace_payment",
        occurred_at=_BASE_TS,
        observed_at=_BASE_TS,
        subject_refs=("listing:eb-123",),
        payload_summary="Paiement reçu pour l'annonce.",
        provenance=(paid_provenance,),
        confidence=0.99,
        source_version="marketplace-ebay-email-v1",
    )
    lifecycle = MarketplaceSaleLifecycle(
        listing_id="eb-123",
        state=SaleLifecycleState.SOLD_PAYMENT_PENDING,
        provenance=(_prov("sale-event"),),
    )

    transition = apply_marketplace_event(lifecycle, paid)

    assert transition.lifecycle.state is SaleLifecycleState.PAID_SHIP_REQUIRED
    assert paid_provenance in transition.lifecycle.provenance
    assert transition.required_action == "ship_item"
    assert transition.action_state is ActionState.USER_DECISION
    assert transition.financial_action is False
    assert transition.payment_observation_only is True
