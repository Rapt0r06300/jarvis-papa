from __future__ import annotations

from decimal import Decimal

from jarvis_papa.banking_intelligence import BankTransaction, BankTransactionStatus
from jarvis_papa.situations import ActionState, MatchState, ProvenanceRef

_BASE_TS = 1_800_000_000.0


def _prov(source_id: str = "bank-fixture") -> ProvenanceRef:
    return ProvenanceRef("synthetic_bank_fixture", source_id, _BASE_TS)


def _tx(
    *,
    amount: str = "-46.90",
    merchant: str = "AMZN MKTP FR",
    reference: str = "BANK-REF-1",
    date: str = "2026-09-01",
) -> BankTransaction:
    return BankTransaction.create(
        booking_date=date,
        value_date=date,
        amount=Decimal(amount),
        currency="EUR",
        raw_description=f"CB {merchant}",
        raw_merchant=merchant,
        normalized_merchant="Amazon" if "AMZN" in merchant else merchant,
        reference=reference,
        status=BankTransactionStatus.BOOKED,
        provenance=(_prov(reference),),
        confidence=0.95,
    )


def test_p6_08_amount_anomaly_explains_baseline_and_insufficient_history() -> None:
    from jarvis_papa.banking_correlation import assess_amount_anomaly

    normal = [Decimal(value) for value in ("9.80", "10.10", "10.40", "9.95", "10.20", "10.05", "9.90", "10.30")]
    outlier = assess_amount_anomaly(Decimal("119.00"), normal)
    assert outlier.is_unusual is True
    assert outlier.sample_sufficient is True
    assert outlier.sample_size == 8
    assert outlier.baseline_amount > Decimal(0)
    assert outlier.reasons
    assert "vérif" in outlier.recommendation.casefold()
    assert outlier.confirmed_fraud is False

    sparse = assess_amount_anomaly(Decimal("119.00"), [Decimal(10), Decimal(11)])
    assert sparse.sample_sufficient is False
    assert sparse.is_unusual is False
    assert "insuff" in " ".join(sparse.reasons).casefold()


def test_p6_09_new_merchant_is_factual_review_signal_not_fraud() -> None:
    from jarvis_papa.banking_correlation import assess_merchant_newness

    result = assess_merchant_newness(
        "Librairie du Port",
        historical_merchants=("Amazon", "PayPal", "Carrefour"),
    )
    assert result.is_new is True
    assert result.action_state is ActionState.VERIFY
    assert result.confirmed_fraud is False
    assert "nouveau" in result.reason.casefold()

    known = assess_merchant_newness("Amazon", historical_merchants=("amazon", "PayPal"))
    assert known.is_new is False


def test_p6_10_unmatched_status_respects_data_freshness_and_priority() -> None:
    from jarvis_papa.banking_correlation import assess_unmatched_transaction

    tx = _tx(merchant="LIBRAIRIE DU PORT", amount="-18.50", reference="UNMATCHED-1")
    result = assess_unmatched_transaction(
        tx,
        matched_situation_ids=(),
        data_available=True,
        data_fresh=True,
        high_risk=False,
    )
    assert result.unmatched is True
    assert result.action_state is ActionState.PAYMENT_REVIEW
    assert result.urgent is False
    assert result.data_available is True
    assert result.data_fresh is True

    unavailable = assess_unmatched_transaction(
        tx,
        matched_situation_ids=(),
        data_available=False,
        data_fresh=False,
        high_risk=False,
    )
    assert unavailable.unmatched is False
    assert unavailable.action_state is ActionState.VERIFY
    assert "donnée" in unavailable.reason.casefold() or "donnee" in unavailable.reason.casefold()


def test_p6_11_expected_refund_tracks_origin_and_overdue_deadline() -> None:
    from jarvis_papa.banking_correlation import ExpectedRefund

    expected = ExpectedRefund.create(
        situation_id="refund-situation-42",
        amount=Decimal("46.90"),
        currency="EUR",
        merchant="Amazon",
        announced_at=_BASE_TS,
        deadline_at=_BASE_TS + 5 * 86400,
        reference="ORDER-42",
        provenance=(_prov("refund-mail-42"),),
    )
    assert expected.situation_id == "refund-situation-42"
    assert expected.provenance[0].source_id == "refund-mail-42"
    assert expected.is_overdue(_BASE_TS + 4 * 86400) is False
    assert expected.is_overdue(_BASE_TS + 6 * 86400) is True


def test_p6_12_refund_reconciliation_requires_strong_evidence() -> None:
    from jarvis_papa.banking_correlation import ExpectedRefund, reconcile_expected_refund

    expected = ExpectedRefund.create(
        situation_id="refund-situation-42",
        amount=Decimal("46.90"),
        currency="EUR",
        merchant="Amazon",
        announced_at=_BASE_TS,
        deadline_at=_BASE_TS + 7 * 86400,
        reference="ORDER-42",
        provenance=(_prov("refund-mail-42"),),
    )
    exact_credit = _tx(amount="46.90", merchant="AMZN REFUND", reference="ORDER-42", date="2026-09-03")
    exact = reconcile_expected_refund(expected, exact_credit)
    assert exact.state is MatchState.CONFIRMED_MATCH
    assert exact.score >= 0.8
    assert exact.selected_id == expected.refund_id
    assert exact.reasons

    near_credit = _tx(amount="45.90", merchant="AMZN REFUND", reference="OTHER", date="2026-09-03")
    near = reconcile_expected_refund(expected, near_credit)
    assert near.state is not MatchState.CONFIRMED_MATCH
    assert near.score < 0.8


def test_p6_13_purchase_correlation_confirms_unique_match_but_not_tie() -> None:
    from jarvis_papa.banking_correlation import OrderEvidence, correlate_order

    tx = _tx(amount="-46.90", merchant="AMZN MKTP FR", reference="ORDER-42", date="2026-09-01")
    order = OrderEvidence(
        order_id="ORDER-42",
        amount=Decimal("46.90"),
        currency="EUR",
        merchant="Amazon",
        event_date="2026-09-01",
        reference="ORDER-42",
        provenance=(_prov("order-42"),),
    )
    unique = correlate_order(tx, (order,))
    assert unique.state is MatchState.CONFIRMED_MATCH
    assert unique.selected_id == "ORDER-42"
    assert unique.score >= 0.8

    tied = correlate_order(
        tx,
        (
            order,
            OrderEvidence(
                order_id="ORDER-43",
                amount=Decimal("46.90"),
                currency="EUR",
                merchant="Amazon",
                event_date="2026-09-01",
                reference="ORDER-42",
                provenance=(_prov("order-43"),),
            ),
        ),
    )
    assert tied.state is not MatchState.CONFIRMED_MATCH
    assert tied.selected_id is None
    assert set(tied.ambiguous_ids) == {"ORDER-42", "ORDER-43"}


def test_p6_14_invoice_correlation_ranks_candidates_and_preserves_ties() -> None:
    from jarvis_papa.banking_correlation import InvoiceEvidence, correlate_invoice

    tx = _tx(amount="-29.99", merchant="ACME CLOUD", reference="INV-2026-9", date="2026-09-02")
    invoice = InvoiceEvidence(
        invoice_id="INV-2026-9",
        amount=Decimal("29.99"),
        currency="EUR",
        merchant="ACME CLOUD",
        event_date="2026-09-02",
        reference="INV-2026-9",
        provenance=(_prov("invoice-9"),),
    )
    unique = correlate_invoice(tx, (invoice,))
    assert unique.state is MatchState.CONFIRMED_MATCH
    assert unique.selected_id == invoice.invoice_id
    assert unique.reasons

    tied = correlate_invoice(
        tx,
        (
            invoice,
            InvoiceEvidence(
                invoice_id="INV-2026-10",
                amount=Decimal("29.99"),
                currency="EUR",
                merchant="ACME CLOUD",
                event_date="2026-09-02",
                reference="INV-2026-9",
                provenance=(_prov("invoice-10"),),
            ),
        ),
    )
    assert tied.state is not MatchState.CONFIRMED_MATCH
    assert tied.selected_id is None
    assert tied.ambiguous_ids
