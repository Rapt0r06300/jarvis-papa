from __future__ import annotations

from decimal import Decimal

from jarvis_papa.situations import ProvenanceRef

_TS = 1_800_300_000.0


def _prov(source: str, source_id: str) -> ProvenanceRef:
    return ProvenanceRef(source, source_id, _TS)


def test_p7_06_correct_invoice_outranks_generic_similar_document() -> None:
    from jarvis_papa.correlation_links import (
        DocumentCandidate,
        SituationEvidence,
        rank_document_candidates,
    )

    situation = SituationEvidence(
        requested_type="facture",
        merchant="Amazon",
        amount=Decimal("46.90"),
        date="2026-09-03",
        order_id="ORDER-42",
        item_names=("casque",),
    )
    candidates = (
        DocumentCandidate(
            "invoice-42",
            "facture",
            "Amazon",
            Decimal("46.90"),
            "2026-09-03",
            "ORDER-42",
            ("casque",),
            (_prov("file", "invoice-42"),),
        ),
        DocumentCandidate(
            "generic-pdf",
            "facture",
            "Autre",
            Decimal("46.90"),
            "2026-09-03",
            "",
            ("casque",),
            (_prov("file", "generic-pdf"),),
        ),
    )
    ranked = rank_document_candidates(situation, candidates)
    assert ranked[0].candidate.document_id == "invoice-42"
    assert ranked[0].score > ranked[1].score
    assert "order_id" in ranked[0].explanations
    assert ranked[1].confirmed is False


def test_p7_07_exact_order_id_confirms_order_invoice_relation() -> None:
    from jarvis_papa.correlation_links import LinkState, link_order_to_invoice

    relation = link_order_to_invoice(
        order_id="ORDER-42",
        order_merchant="Amazon",
        invoice_order_id="ORDER-42",
        invoice_merchant="Amazon",
        provenance=(_prov("order", "ORDER-42"), _prov("file", "invoice-42")),
    )
    assert relation.state is LinkState.CONFIRMED
    assert relation.confidence >= 0.9
    assert {ref.source for ref in relation.provenance} == {"order", "file"}

    weak = link_order_to_invoice(
        order_id="ORDER-42",
        order_merchant="Amazon",
        invoice_order_id="",
        invoice_merchant="Amazon",
        provenance=(_prov("order", "ORDER-42"), _prov("file", "unknown")),
    )
    assert weak.state is not LinkState.CONFIRMED


def test_p7_08_document_request_returns_proposals_never_auto_send() -> None:
    from jarvis_papa.correlation_links import (
        DocumentCandidate,
        SituationEvidence,
        match_document_request,
    )

    request = SituationEvidence("facture", "Amazon", Decimal("46.90"), "2026-09-03", "ORDER-42", ())
    candidates = (
        DocumentCandidate(
            "invoice-42",
            "facture",
            "Amazon",
            Decimal("46.90"),
            "2026-09-03",
            "ORDER-42",
            (),
            (_prov("file", "invoice-42"),),
        ),
    )
    proposal = match_document_request(request, candidates)
    assert proposal.candidates[0].candidate.document_id == "invoice-42"
    assert proposal.automatic_send_allowed is False
    assert "facture" in proposal.search_facts
    assert "Amazon" in proposal.search_facts
    assert "ORDER-42" in proposal.search_facts


def test_p7_09_transaction_invoice_match_uses_combined_evidence_and_ties() -> None:
    from jarvis_papa.correlation_links import (
        InvoiceEvidence,
        LinkState,
        TransactionEvidence,
        link_transaction_to_invoice,
    )

    transaction = TransactionEvidence(Decimal("-46.90"), "2026-09-03", "Amazon", "ORDER-42")
    unique = link_transaction_to_invoice(
        transaction,
        (
            InvoiceEvidence("invoice-42", Decimal("46.90"), "2026-09-03", "Amazon", "ORDER-42"),
            InvoiceEvidence("other", Decimal("99.00"), "2026-09-01", "Other", ""),
        ),
    )
    assert unique.state in {LinkState.LIKELY, LinkState.CONFIRMED}
    assert unique.document_id == "invoice-42"
    assert unique.confidence >= 0.8

    tied = link_transaction_to_invoice(
        transaction,
        (
            InvoiceEvidence("a", Decimal("46.90"), "2026-09-03", "Amazon", ""),
            InvoiceEvidence("b", Decimal("46.90"), "2026-09-03", "Amazon", ""),
        ),
    )
    assert tied.state is LinkState.AMBIGUOUS
    assert tied.document_id == ""


def test_p7_10_exact_tracking_confirms_single_shipment_relation() -> None:
    from jarvis_papa.correlation_links import LinkState, ShipmentEvidence, link_shipment_to_order

    exact = link_shipment_to_order(
        ShipmentEvidence("TRACK-9", "ORDER-42", "Mondial Relay"),
        order_id="ORDER-42",
        known_tracking_ids=("TRACK-9",),
        merchant="Amazon",
    )
    assert exact.state is LinkState.CONFIRMED
    assert exact.confidence >= 0.9
    assert "tracking_id" in exact.reasons

    heuristic = link_shipment_to_order(
        ShipmentEvidence("", "", "Carrier"),
        order_id="ORDER-42",
        known_tracking_ids=(),
        merchant="Amazon",
    )
    assert heuristic.state is not LinkState.CONFIRMED
