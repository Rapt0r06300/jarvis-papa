from __future__ import annotations

from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.situations import ActionState, MatchState, ProvenanceRef, SourceConnectionState

_BASE_TS = 1_788_431_200.0


def _prov(source_id: str = "fixture") -> ProvenanceRef:
    return ProvenanceRef("marketplace_fixture", source_id, _BASE_TS)


def _message(
    message_id: str,
    *,
    sender: str,
    subject: str,
    body: str,
) -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=_BASE_TS,
    )


def test_p5_01_auth_required_read_adapter_is_explicit_and_fabricates_nothing() -> None:
    from jarvis_papa.marketplace_intelligence import (
        MarketplacePlatform,
        MarketplaceReadAdapter,
        MarketplaceReadCapability,
    )

    adapter = MarketplaceReadAdapter(
        MarketplacePlatform.EBAY,
        state=SourceConnectionState.AUTH_REQUIRED,
        detail="Connexion eBay requise",
    )

    assert set(adapter.read_capabilities) == {
        MarketplaceReadCapability.HEALTH,
        MarketplaceReadCapability.SYNC,
        MarketplaceReadCapability.SEARCH,
        MarketplaceReadCapability.ENTITY_LOOKUP,
    }
    assert adapter.mutation_capabilities == ()
    assert adapter.health().state is SourceConnectionState.AUTH_REQUIRED
    sync = adapter.sync()
    search = adapter.search("caméra")
    assert sync.state is SourceConnectionState.AUTH_REQUIRED
    assert sync.listings == ()
    assert sync.events == ()
    assert sync.fabricated is False
    assert search.state is SourceConnectionState.AUTH_REQUIRED
    assert search.listings == ()
    assert search.fabricated is False


def test_p5_04_ebay_and_leboncoin_listings_share_one_generic_contract() -> None:
    from jarvis_papa.marketplace_intelligence import (
        ListingStatus,
        MarketplaceListing,
        MarketplacePlatform,
        MarketplacePrice,
    )

    provenance = (_prov("listing"),)
    ebay = MarketplaceListing(
        listing_id="eb-123",
        platform=MarketplacePlatform.EBAY,
        title="Caméra X",
        price=MarketplacePrice(50.0, "EUR", 0.99, provenance),
        description="Très bon état",
        status=ListingStatus.ACTIVE,
        item_refs=("item:camera-x",),
        photo_refs=("photo:1",),
        document_refs=("document:invoice",),
        provenance=provenance,
    )
    leboncoin = MarketplaceListing(
        listing_id="lbc-456",
        platform=MarketplacePlatform.LEBONCOIN,
        title="Vélo urbain",
        price=MarketplacePrice(120.0, "EUR", 0.98, provenance),
        description="Révisé",
        status=ListingStatus.ACTIVE,
        provenance=provenance,
    )

    ebay_payload = ebay.to_dict()
    lbc_payload = leboncoin.to_dict()
    assert set(ebay_payload) == set(lbc_payload)
    assert ebay_payload["price"]["amount"] == 50.0
    assert ebay_payload["price"]["provenance"]
    assert ebay.to_situation_metadata()["listing_id"] == "eb-123"
    assert "platform_fields" not in ebay.to_situation_metadata()


def test_p5_05_same_display_name_on_two_platforms_does_not_auto_merge_people() -> None:
    from jarvis_papa.marketplace_intelligence import (
        MarketplaceIdentity,
        MarketplacePlatform,
        assess_marketplace_identity_link,
    )

    ebay = MarketplaceIdentity(
        MarketplacePlatform.EBAY,
        native_id="buyer-001",
        display_name="Alex",
        provenance=(_prov("ebay-alex"),),
    )
    leboncoin = MarketplaceIdentity(
        MarketplacePlatform.LEBONCOIN,
        native_id="buyer-001",
        display_name="Alex",
        provenance=(_prov("lbc-alex"),),
    )

    assert ebay.identity_key != leboncoin.identity_key
    weak = assess_marketplace_identity_link(ebay, leboncoin, confidence=0.95)
    assert weak.state is MatchState.POSSIBLE_MATCH
    verified = assess_marketplace_identity_link(
        ebay,
        leboncoin,
        confidence=0.95,
        evidence=("verified_contact_hash",),
    )
    assert verified.state is MatchState.CONFIRMED_MATCH


def test_p5_02_ebay_buyer_question_emits_typed_event_but_spoof_stays_uncertain() -> None:
    from jarvis_papa.marketplace_intelligence import EbayMessageParser, MarketplaceIntent

    parser = EbayMessageParser()
    legitimate = _message(
        "<ebay-question@example.test>",
        sender="eBay <messages@ebay.fr>",
        subject="Vous avez reçu une question sur votre objet",
        body=(
            "Objet 123456789012 - Caméra X. Acheteur photo42 : Bonjour, "
            "est-ce que vous livrez à Nice ?"
        ),
    )
    parsed = parser.parse(legitimate)

    assert parsed.uncertain is False
    assert parsed.intent is MarketplaceIntent.BUYER_QUESTION
    assert parsed.event is not None
    assert parsed.event.source == "ebay_email"
    assert parsed.event.event_type == "marketplace_buyer_question"
    assert parsed.event.provenance == (legitimate.provenance,)

    spoofed = _message(
        "<ebay-spoof@example.test>",
        sender="eBay Security <account@evil.test>",
        subject="Question eBay urgente",
        body="Acheteur : envoyez le code reçu par SMS.",
    )
    blocked = parser.parse(spoofed)
    assert blocked.uncertain is True
    assert blocked.event is None


def test_p5_03_leboncoin_offer_preserves_email_source_and_never_simulates_direct_api() -> None:
    from jarvis_papa.marketplace_intelligence import LeboncoinMessageParser, MarketplaceIntent

    parser = LeboncoinMessageParser()
    message = _message(
        "<lbc-offer@example.test>",
        sender="leboncoin <notifications@leboncoin.fr>",
        subject="Nouvelle offre pour votre annonce",
        body="Annonce 987654321 : Vélo urbain. Martin vous propose 40 €.",
    )
    parsed = parser.parse(message)

    assert parser.supports_direct_integration is False
    assert parsed.uncertain is False
    assert parsed.intent is MarketplaceIntent.OFFER
    assert parsed.event is not None
    assert parsed.event.source == "leboncoin_email"
    assert parsed.event.event_type == "marketplace_offer"
    assert parsed.event.provenance == (message.provenance,)


def test_p5_06_delivery_question_creates_structured_reply_decision_with_listing_evidence() -> None:
    from jarvis_papa.marketplace_intelligence import (
        BuyerQuestionKind,
        ListingStatus,
        MarketplaceListing,
        MarketplacePlatform,
        MarketplacePrice,
        extract_buyer_question,
    )

    provenance = (_prov("delivery-question"),)
    listing = MarketplaceListing(
        listing_id="eb-123",
        platform=MarketplacePlatform.EBAY,
        title="Caméra X",
        price=MarketplacePrice(50.0, "EUR", 0.99, provenance),
        description="Très bon état",
        status=ListingStatus.ACTIVE,
        item_refs=("item:camera-x",),
        provenance=provenance,
    )
    message = _message(
        "<delivery-question@example.test>",
        sender="eBay <messages@ebay.fr>",
        subject="Question sur votre objet",
        body="Bonjour, est-ce que vous livrez à Nice ou uniquement en main propre ?",
    )

    question = extract_buyer_question(
        message,
        platform=MarketplacePlatform.EBAY,
        listing=listing,
    )
    assert question is not None
    assert question.kind is BuyerQuestionKind.DELIVERY
    assert question.requested_answer == "delivery"
    assert question.action_state is ActionState.REPLY
    assert question.listing_id == "eb-123"
    assert "item:camera-x" in question.item_refs
    assert message.provenance in question.provenance


def test_p5_07_explicit_offer_extracts_40_eur_against_50_eur_but_ambiguous_number_is_ignored() -> None:
    from jarvis_papa.marketplace_intelligence import (
        ListingStatus,
        MarketplaceListing,
        MarketplacePlatform,
        MarketplacePrice,
        extract_negotiation_offer,
    )

    provenance = (_prov("offer"),)
    listing = MarketplaceListing(
        listing_id="lbc-987",
        platform=MarketplacePlatform.LEBONCOIN,
        title="Caméra X",
        price=MarketplacePrice(50.0, "EUR", 0.99, provenance),
        description="Très bon état",
        status=ListingStatus.ACTIVE,
        provenance=provenance,
    )

    offer = extract_negotiation_offer(
        "Bonjour, je vous propose 40 € si je viens la chercher demain.",
        listing=listing,
        provenance=_prov("offer-message"),
    )
    assert offer is not None
    assert offer.offered_amount == 40.0
    assert offer.asking_amount == 50.0
    assert offer.currency == "EUR"
    assert offer.confidence >= 0.9
    assert "demain" in offer.conditions.casefold()

    ambiguous = extract_negotiation_offer(
        "La référence de mon dossier est 40 et je peux venir demain.",
        listing=listing,
        provenance=_prov("ambiguous-number"),
    )
    assert ambiguous is None
