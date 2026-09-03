from __future__ import annotations

from jarvis_papa.situations import ProvenanceRef

_TS = 1_800_200_000.0


def _prov(source: str, source_id: str) -> ProvenanceRef:
    return ProvenanceRef(source, source_id, _TS)


def test_p7_01_service_links_normalized_entities_with_evidence() -> None:
    from jarvis_papa.correlation_foundations import CorrelationEntity, CrossSourceCorrelationService

    service = CrossSourceCorrelationService()
    mail = CorrelationEntity("mail", "mail-1", {"order_id": "ORDER-42"}, (_prov("mail", "mail-1"),))
    shipment = CorrelationEntity(
        "shipment",
        "ship-1",
        {"order_id": "ORDER-42", "tracking_id": "TRACK-9"},
        (_prov("carrier", "ship-1"),),
    )
    invoice = CorrelationEntity("document", "inv-1", {"order_id": "ORDER-42"}, (_prov("file", "inv-1"),))

    result = service.correlate((mail, shipment, invoice))
    assert result.linked_entity_ids == ("inv-1", "mail-1", "ship-1")
    assert result.confidence >= 0.8
    assert result.evidence
    assert {ref.source for ref in result.provenance} == {"mail", "carrier", "file"}


def test_p7_02_strong_identifier_outweighs_date_only_similarity() -> None:
    from jarvis_papa.correlation_foundations import (
        EvidenceSignal,
        EvidenceStrength,
        score_correlation_evidence,
    )

    strong = score_correlation_evidence(
        (EvidenceSignal("tracking_id", EvidenceStrength.STRONG, True, "TRACK-9 exact"),)
    )
    weak = score_correlation_evidence(
        (
            EvidenceSignal("same_date", EvidenceStrength.WEAK, True, "same calendar date"),
            EvidenceSignal("merchant", EvidenceStrength.WEAK, True, "similar merchant"),
        )
    )
    assert strong.score > weak.score
    assert strong.explanations == ("tracking_id: TRACK-9 exact",)
    assert strong.strength is EvidenceStrength.STRONG


def test_p7_03_merchant_alias_registry_preserves_raw_and_supports_rejection() -> None:
    from jarvis_papa.correlation_foundations import MerchantAliasRegistry

    registry = MerchantAliasRegistry()
    registry.register(
        canonical="Amazon",
        alias="AMZN MKTP FR",
        confidence=0.96,
        scope="bank",
        provenance=_prov("bank", "alias-1"),
    )
    resolved = registry.resolve("AMZN MKTP FR", scope="bank")
    assert resolved.matched is True
    assert resolved.canonical == "Amazon"
    assert resolved.raw == "AMZN MKTP FR"
    assert resolved.provenance.source_id == "alias-1"

    registry.reject("AMZN MKTP FR", scope="bank")
    rejected = registry.resolve("AMZN MKTP FR", scope="bank")
    assert rejected.matched is False
    assert rejected.raw == "AMZN MKTP FR"
    assert registry.resolve("AM", scope="bank").matched is False


def test_p7_04_person_alias_needs_more_than_same_name() -> None:
    from jarvis_papa.correlation_foundations import PersonIdentity, assess_person_relation

    first = PersonIdentity("email:jean-a", "Jean", "jean.a@example.test", "", _prov("mail", "jean-a"))
    second = PersonIdentity("market:jean-b", "Jean", "", "seller-99", _prov("market", "jean-b"))
    same_name_only = assess_person_relation(first, second)
    assert same_name_only.confirmed is False
    assert same_name_only.confidence < 0.8
    assert {identity.native_id for identity in same_name_only.identities} == {"email:jean-a", "market:jean-b"}

    third = PersonIdentity("market:jean-c", "Jean", "jean.a@example.test", "seller-100", _prov("market", "jean-c"))
    stronger = assess_person_relation(first, third)
    assert stronger.confirmed is True
    assert stronger.confidence >= 0.8


def test_p7_05_document_dedupe_keeps_all_physical_locations() -> None:
    from jarvis_papa.correlation_foundations import DocumentOccurrence, deduplicate_documents

    first = DocumentOccurrence("/downloads/invoice.pdf", b"same invoice", {"merchant": "Amazon"})
    second = DocumentOccurrence("D:/Archive/invoice-copy.pdf", b"same invoice", {"merchant": "Amazon"})
    other = DocumentOccurrence("/downloads/other.pdf", b"other", {"merchant": "Other"})

    logical = deduplicate_documents((first, second, other))
    assert len(logical) == 2
    duplicate = next(item for item in logical if len(item.locations) == 2)
    assert duplicate.content_hash
    assert set(duplicate.locations) == {"/downloads/invoice.pdf", "D:/Archive/invoice-copy.pdf"}
