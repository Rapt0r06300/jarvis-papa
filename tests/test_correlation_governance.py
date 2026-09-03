from __future__ import annotations

from jarvis_papa.situations import ProvenanceRef

_TS = 1_800_400_000.0


def _prov(source: str, source_id: str) -> ProvenanceRef:
    return ProvenanceRef(source, source_id, _TS)


def test_p7_11_platform_listing_id_links_deterministically_but_name_only_does_not() -> None:
    from jarvis_papa.correlation_governance import (
        MarketplaceConversation,
        MarketplaceListing,
        link_marketplace_conversation,
    )

    listings = (
        MarketplaceListing("ebay", "listing-42", "Casque Sony", "item-42", (_prov("market", "listing-42"),)),
        MarketplaceListing("ebay", "listing-99", "Casque Sony", "item-99", (_prov("market", "listing-99"),)),
    )
    exact = link_marketplace_conversation(
        MarketplaceConversation("ebay", "conv-1", "listing-42", "Casque Sony", (_prov("market", "conv-1"),)),
        listings,
    )
    assert exact.confirmed is True
    assert exact.listing_id == "listing-42"
    assert "platform_listing_id" in exact.reasons

    ambiguous = link_marketplace_conversation(
        MarketplaceConversation("ebay", "conv-2", "", "Casque Sony", (_prov("market", "conv-2"),)),
        listings,
    )
    assert ambiguous.confirmed is False
    assert ambiguous.listing_id == ""


def test_p7_12_relation_split_is_reversible_and_preserves_sources() -> None:
    from jarvis_papa.correlation_governance import RelationStore

    store = RelationStore()
    store.merge("relation-1", ("order-42", "invoice-42"), evidence_version="ev-1", provenance=(_prov("user", "merge"),))
    store.split("relation-1", actor="Robert", provenance=_prov("user", "split"))
    relation = store.get("relation-1")
    assert relation.active is False
    assert relation.source_entity_ids == ("invoice-42", "order-42")
    assert store.source_entity_ids == {"order-42", "invoice-42"}
    store.restore("relation-1", actor="Robert", provenance=_prov("user", "restore"))
    assert store.get("relation-1").active is True
    assert {event.action for event in store.audit_events()} >= {"merge", "split", "restore"}


def test_p7_13_plain_reject_blocks_auto_confirm_until_new_evidence() -> None:
    from jarvis_papa.correlation_governance import RelationReviewDecision, RelationStore

    store = RelationStore()
    store.propose("relation-2", ("order-7", "invoice-7"), evidence_version="ev-1", provenance=(_prov("engine", "p"),))
    rejected = store.review(
        "relation-2",
        RelationReviewDecision.REJECT,
        actor="Robert",
        provenance=_prov("user", "reject"),
    )
    assert rejected.active is False
    assert rejected.user_label == "Non"
    assert "score" not in rejected.user_label.casefold()
    assert store.can_auto_confirm("relation-2", evidence_version="ev-1") is False
    assert store.can_auto_confirm("relation-2", evidence_version="ev-2") is True


def test_p7_14_manual_reject_has_traceable_non_secret_audit_event() -> None:
    from jarvis_papa.correlation_governance import RelationReviewDecision, RelationStore

    store = RelationStore()
    store.propose("relation-3", ("mail-1", "listing-1"), evidence_version="ev-1", provenance=(_prov("engine", "p"),))
    store.review(
        "relation-3",
        RelationReviewDecision.REJECT,
        actor="Robert",
        provenance=_prov("user", "reject"),
        metadata={"reason": "pas la même annonce", "otp_code": "123456"},
    )
    event = store.audit_events()[-1]
    assert event.action == "reject"
    assert event.relation_id == "relation-3"
    assert event.evidence_version == "ev-1"
    assert "pas la même annonce" in event.metadata.values()
    assert "123456" not in repr(event)
    assert "otp_code" not in event.metadata


def test_p7_15_unified_search_contract_keeps_plain_type_source_and_provenance() -> None:
    from jarvis_papa.correlation_governance import SearchSourceResult, unified_search

    results = unified_search(
        "amazon facture",
        (
            SearchSourceResult("situation", "s-1", "Colis Amazon", 0.91, "Situations", (_prov("situation", "s-1"),)),
            SearchSourceResult("document", "d-1", "Facture Amazon", 0.96, "Documents", (_prov("file", "d-1"),)),
            SearchSourceResult("mail", "m-1", "Amazon expédition", 0.72, "Mails", (_prov("mail", "m-1"),)),
        ),
    )
    assert [item.result_type for item in results[:2]] == ["document", "situation"]
    assert {item.source for item in results} >= {"Documents", "Situations", "Mails"}
    assert all(item.provenance for item in results)
    assert all("::" not in item.source for item in results)
