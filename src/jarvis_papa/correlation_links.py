from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .situations import ProvenanceRef


class LinkState(StrEnum):
    POSSIBLE = "possible"
    LIKELY = "likely"
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SituationEvidence:
    requested_type: str
    merchant: str
    amount: Decimal
    date: str
    order_id: str
    item_names: tuple[str, ...]


@dataclass(frozen=True)
class DocumentCandidate:
    document_id: str
    document_type: str
    merchant: str
    amount: Decimal
    date: str
    order_id: str
    item_names: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True)
class RankedDocumentCandidate:
    candidate: DocumentCandidate
    score: float
    explanations: tuple[str, ...]
    confirmed: bool


@dataclass(frozen=True)
class LinkResult:
    state: LinkState
    confidence: float
    reasons: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...] = ()
    document_id: str = ""


@dataclass(frozen=True)
class DocumentRequestProposal:
    candidates: tuple[RankedDocumentCandidate, ...]
    search_facts: tuple[str, ...]
    automatic_send_allowed: bool = False


@dataclass(frozen=True)
class TransactionEvidence:
    amount: Decimal
    date: str
    merchant: str
    order_id: str


@dataclass(frozen=True)
class InvoiceEvidence:
    document_id: str
    amount: Decimal
    date: str
    merchant: str
    order_id: str


@dataclass(frozen=True)
class ShipmentEvidence:
    tracking_id: str
    order_id: str
    carrier: str


def _norm(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _money_equal(left: Decimal, right: Decimal) -> bool:
    return abs(left) == abs(right)


def rank_document_candidates(
    situation: SituationEvidence,
    candidates: tuple[DocumentCandidate, ...],
) -> tuple[RankedDocumentCandidate, ...]:
    ranked: list[RankedDocumentCandidate] = []
    requested_items = {_norm(item) for item in situation.item_names if item.strip()}
    for candidate in candidates:
        score = 0.0
        explanations: list[str] = []
        if situation.requested_type and _norm(candidate.document_type) == _norm(situation.requested_type):
            score += 0.15
            explanations.append("document_type")
        if situation.merchant and _norm(candidate.merchant) == _norm(situation.merchant):
            score += 0.20
            explanations.append("merchant")
        if _money_equal(candidate.amount, situation.amount):
            score += 0.15
            explanations.append("amount")
        if situation.date and candidate.date == situation.date:
            score += 0.10
            explanations.append("date")
        if situation.order_id and candidate.order_id and _norm(candidate.order_id) == _norm(situation.order_id):
            score += 0.35
            explanations.append("order_id")
        candidate_items = {_norm(item) for item in candidate.item_names if item.strip()}
        if requested_items and requested_items.intersection(candidate_items):
            score += 0.05
            explanations.append("item_names")
        score = min(score, 1.0)
        ranked.append(
            RankedDocumentCandidate(
                candidate=candidate,
                score=score,
                explanations=tuple(explanations),
                confirmed=score >= 0.90 and "order_id" in explanations,
            )
        )
    return tuple(sorted(ranked, key=lambda item: (-item.score, item.candidate.document_id)))


def link_order_to_invoice(
    *,
    order_id: str,
    order_merchant: str,
    invoice_order_id: str,
    invoice_merchant: str,
    provenance: tuple[ProvenanceRef, ...],
) -> LinkResult:
    exact_order = bool(order_id and invoice_order_id and _norm(order_id) == _norm(invoice_order_id))
    same_merchant = bool(order_merchant and invoice_merchant and _norm(order_merchant) == _norm(invoice_merchant))
    if exact_order:
        reasons = ("order_id", "merchant") if same_merchant else ("order_id",)
        return LinkResult(LinkState.CONFIRMED, 0.98 if same_merchant else 0.94, reasons, provenance)
    if same_merchant:
        return LinkResult(LinkState.POSSIBLE, 0.45, ("merchant",), provenance)
    return LinkResult(LinkState.POSSIBLE, 0.10, (), provenance)


def match_document_request(
    request: SituationEvidence,
    candidates: tuple[DocumentCandidate, ...],
) -> DocumentRequestProposal:
    ranked = rank_document_candidates(request, candidates)
    facts = tuple(
        value
        for value in (
            request.requested_type,
            request.merchant,
            str(abs(request.amount)) if request.amount else "",
            request.date,
            request.order_id,
            *request.item_names,
        )
        if str(value).strip()
    )
    return DocumentRequestProposal(candidates=ranked, search_facts=facts, automatic_send_allowed=False)


def _invoice_match_score(transaction: TransactionEvidence, invoice: InvoiceEvidence) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    reasons: list[str] = []
    if _money_equal(transaction.amount, invoice.amount):
        score += 0.30
        reasons.append("amount")
    if transaction.date and transaction.date == invoice.date:
        score += 0.20
        reasons.append("date")
    if transaction.merchant and _norm(transaction.merchant) == _norm(invoice.merchant):
        score += 0.20
        reasons.append("merchant")
    if transaction.order_id and invoice.order_id and _norm(transaction.order_id) == _norm(invoice.order_id):
        score += 0.30
        reasons.append("order_id")
    return min(score, 1.0), tuple(reasons)


def link_transaction_to_invoice(
    transaction: TransactionEvidence,
    invoices: tuple[InvoiceEvidence, ...],
) -> LinkResult:
    if not invoices:
        return LinkResult(LinkState.POSSIBLE, 0.0, ())
    scored = sorted(
        ((invoice, *_invoice_match_score(transaction, invoice)) for invoice in invoices),
        key=lambda item: (-item[1], item[0].document_id),
    )
    best_invoice, best_score, best_reasons = scored[0]
    ties = [item for item in scored if item[1] == best_score]
    if len(ties) > 1 and best_score > 0:
        return LinkResult(LinkState.AMBIGUOUS, best_score, best_reasons)
    if best_score >= 0.90:
        state = LinkState.CONFIRMED
    elif best_score >= 0.70:
        state = LinkState.LIKELY
    else:
        state = LinkState.POSSIBLE
    return LinkResult(state, best_score, best_reasons, document_id=best_invoice.document_id)


def link_shipment_to_order(
    shipment: ShipmentEvidence,
    *,
    order_id: str,
    known_tracking_ids: tuple[str, ...],
    merchant: str,
) -> LinkResult:
    del merchant
    normalized_tracking = {_norm(value) for value in known_tracking_ids if value.strip()}
    if shipment.tracking_id and _norm(shipment.tracking_id) in normalized_tracking:
        reasons = ["tracking_id"]
        confidence = 0.96
        if shipment.order_id and order_id and _norm(shipment.order_id) == _norm(order_id):
            reasons.append("order_id")
            confidence = 0.99
        return LinkResult(LinkState.CONFIRMED, confidence, tuple(reasons))
    if shipment.order_id and order_id and _norm(shipment.order_id) == _norm(order_id):
        return LinkResult(LinkState.CONFIRMED, 0.94, ("order_id",))
    return LinkResult(LinkState.POSSIBLE, 0.15, ())
