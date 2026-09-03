from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from jarvis_papa.banking_intelligence import BankTransaction, normalize_bank_merchant
from jarvis_papa.situations import ActionState, MatchState, ProvenanceRef


@dataclass(frozen=True, slots=True)
class AmountAnomalyAssessment:
    is_unusual: bool
    sample_sufficient: bool
    sample_size: int
    baseline_amount: Decimal
    deviation_ratio: float
    reasons: tuple[str, ...]
    recommendation: str
    confirmed_fraud: bool = False


def assess_amount_anomaly(
    amount: Decimal,
    history: list[Decimal] | tuple[Decimal, ...],
    *,
    min_samples: int = 5,
) -> AmountAnomalyAssessment:
    values = [abs(Decimal(value)) for value in history]
    sample_size = len(values)
    if sample_size < max(3, int(min_samples)):
        baseline = median(values) if values else Decimal(0)
        return AmountAnomalyAssessment(
            is_unusual=False,
            sample_sufficient=False,
            sample_size=sample_size,
            baseline_amount=baseline,
            deviation_ratio=0.0,
            reasons=(
                "Historique insuffisant pour qualifier statistiquement ce montant.",
            ),
            recommendation="Conserver l'opération en observation sans conclusion automatique.",
        )

    baseline = median(values)
    deviations = [abs(value - baseline) for value in values]
    mad = median(deviations)
    observed = abs(Decimal(amount))
    relative_threshold = baseline * Decimal(3)
    robust_threshold = baseline + mad * Decimal(6)
    threshold = max(relative_threshold, robust_threshold, Decimal("0.01"))
    unusual = observed >= threshold
    ratio = float(observed / baseline) if baseline > 0 else 0.0
    if unusual:
        reasons = (
            f"Montant observé {observed} supérieur au niveau habituel médian {baseline}.",
            f"Seuil prudent calculé à {threshold} sur {sample_size} opérations comparables.",
        )
        recommendation = "Cette opération mérite une vérification avant toute conclusion."
    else:
        reasons = (
            f"Montant compatible avec le niveau habituel médian {baseline} sur {sample_size} observations.",
        )
        recommendation = "Aucune anomalie de montant forte détectée sur cet historique local."
    return AmountAnomalyAssessment(
        is_unusual=unusual,
        sample_sufficient=True,
        sample_size=sample_size,
        baseline_amount=baseline,
        deviation_ratio=ratio,
        reasons=reasons,
        recommendation=recommendation,
    )


@dataclass(frozen=True, slots=True)
class MerchantNewnessAssessment:
    merchant: str
    is_new: bool
    reason: str
    action_state: ActionState
    confirmed_fraud: bool = False


def assess_merchant_newness(
    merchant: str,
    *,
    historical_merchants: tuple[str, ...] | list[str],
) -> MerchantNewnessAssessment:
    normalized = normalize_bank_merchant(merchant).normalized.casefold().strip()
    known = {
        normalize_bank_merchant(item).normalized.casefold().strip()
        for item in historical_merchants
        if str(item).strip()
    }
    is_new = bool(normalized) and normalized not in known
    if is_new:
        return MerchantNewnessAssessment(
            merchant=merchant,
            is_new=True,
            reason="Marchand nouveau dans l'historique local disponible; cela ne prouve pas une fraude.",
            action_state=ActionState.VERIFY,
        )
    return MerchantNewnessAssessment(
        merchant=merchant,
        is_new=False,
        reason="Marchand déjà observé dans l'historique local disponible.",
        action_state=ActionState.NO_ACTION,
    )


@dataclass(frozen=True, slots=True)
class UnmatchedTransactionAssessment:
    transaction_id: str
    unmatched: bool
    data_available: bool
    data_fresh: bool
    urgent: bool
    action_state: ActionState
    reason: str


def assess_unmatched_transaction(
    transaction: BankTransaction,
    *,
    matched_situation_ids: tuple[str, ...] | list[str],
    data_available: bool,
    data_fresh: bool,
    high_risk: bool,
) -> UnmatchedTransactionAssessment:
    if not data_available or not data_fresh:
        return UnmatchedTransactionAssessment(
            transaction_id=transaction.transaction_id,
            unmatched=False,
            data_available=data_available,
            data_fresh=data_fresh,
            urgent=False,
            action_state=ActionState.VERIFY,
            reason="Données de rapprochement indisponibles ou trop anciennes pour conclure qu'une opération est non appariée.",
        )
    if matched_situation_ids:
        return UnmatchedTransactionAssessment(
            transaction_id=transaction.transaction_id,
            unmatched=False,
            data_available=True,
            data_fresh=True,
            urgent=False,
            action_state=ActionState.READ_ONLY,
            reason="Une situation connue est déjà reliée à cette opération.",
        )
    return UnmatchedTransactionAssessment(
        transaction_id=transaction.transaction_id,
        unmatched=True,
        data_available=True,
        data_fresh=True,
        urgent=bool(high_risk),
        action_state=ActionState.PAYMENT_REVIEW,
        reason=(
            "Aucune situation connue ne correspond dans les données fraîches disponibles; "
            "une vérification est proposée sans conclure à une fraude."
        ),
    )


@dataclass(frozen=True, slots=True)
class ExpectedRefund:
    refund_id: str
    situation_id: str
    amount: Decimal
    currency: str
    merchant: str
    announced_at: float
    deadline_at: float
    reference: str
    provenance: tuple[ProvenanceRef, ...]

    @classmethod
    def create(
        cls,
        *,
        situation_id: str,
        amount: Decimal,
        currency: str,
        merchant: str,
        announced_at: float,
        deadline_at: float,
        reference: str,
        provenance: tuple[ProvenanceRef, ...],
    ) -> ExpectedRefund:
        clean_amount = abs(Decimal(amount)).normalize()
        clean_currency = str(currency).strip().upper()
        stable = "\x1f".join(
            (
                str(situation_id).strip(),
                format(clean_amount, "f"),
                clean_currency,
                str(merchant).strip().casefold(),
                str(reference).strip().casefold(),
                str(float(deadline_at)),
            )
        )
        refund_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]
        return cls(
            refund_id=refund_id,
            situation_id=str(situation_id).strip(),
            amount=clean_amount,
            currency=clean_currency,
            merchant=str(merchant).strip(),
            announced_at=float(announced_at),
            deadline_at=float(deadline_at),
            reference=str(reference).strip(),
            provenance=tuple(provenance),
        )

    def is_overdue(self, now: float) -> bool:
        return float(now) > self.deadline_at


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    state: MatchState
    selected_id: str | None
    score: float
    reasons: tuple[str, ...]
    ambiguous_ids: tuple[str, ...] = ()


def _state_for_score(score: float) -> MatchState:
    if score >= 0.80:
        return MatchState.CONFIRMED_MATCH
    if score >= 0.55:
        return MatchState.LIKELY_MATCH
    return MatchState.POSSIBLE_MATCH


def _normalized_merchant(value: str) -> str:
    return normalize_bank_merchant(value).normalized.casefold().strip()


def reconcile_expected_refund(
    expected: ExpectedRefund,
    transaction: BankTransaction,
) -> CorrelationResult:
    score = 0.0
    reasons: list[str] = []
    observed_amount = abs(transaction.amount)
    if observed_amount == expected.amount:
        score += 0.35
        reasons.append("Montant du crédit identique au remboursement attendu.")
    elif expected.amount > 0:
        difference_ratio = abs(observed_amount - expected.amount) / expected.amount
        if difference_ratio <= Decimal("0.05"):
            score += 0.10
            reasons.append("Montant proche, mais non identique, du remboursement attendu.")
    if transaction.currency == expected.currency:
        score += 0.10
        reasons.append("Devise identique.")
    if _normalized_merchant(transaction.normalized_merchant or transaction.raw_merchant) == _normalized_merchant(expected.merchant):
        score += 0.20
        reasons.append("Marchand compatible avec le remboursement attendu.")
    if expected.reference and transaction.reference.casefold() == expected.reference.casefold():
        score += 0.35
        reasons.append("Référence bancaire identique à la référence du remboursement.")
    score = min(score, 1.0)
    return CorrelationResult(
        state=_state_for_score(score),
        selected_id=expected.refund_id if score >= 0.55 else None,
        score=score,
        reasons=tuple(reasons) or ("Aucun élément de rapprochement suffisamment fort.",),
    )


@dataclass(frozen=True, slots=True)
class OrderEvidence:
    order_id: str
    amount: Decimal
    currency: str
    merchant: str
    event_date: str
    reference: str
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True, slots=True)
class InvoiceEvidence:
    invoice_id: str
    amount: Decimal
    currency: str
    merchant: str
    event_date: str
    reference: str
    provenance: tuple[ProvenanceRef, ...]


def _score_evidence(
    transaction: BankTransaction,
    *,
    amount: Decimal,
    currency: str,
    merchant: str,
    event_date: str,
    reference: str,
) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    reasons: list[str] = []
    if abs(transaction.amount) == abs(Decimal(amount)):
        score += 0.35
        reasons.append("Montant identique.")
    if transaction.currency == str(currency).strip().upper():
        score += 0.10
        reasons.append("Devise identique.")
    if _normalized_merchant(transaction.normalized_merchant or transaction.raw_merchant) == _normalized_merchant(merchant):
        score += 0.25
        reasons.append("Marchand compatible.")
    if transaction.booking_date == str(event_date).strip():
        score += 0.15
        reasons.append("Date identique.")
    if reference and transaction.reference.casefold() == str(reference).strip().casefold():
        score += 0.15
        reasons.append("Référence identique.")
    return min(score, 1.0), tuple(reasons)


def _rank_candidates(
    candidates: list[tuple[str, float, tuple[str, ...]]],
) -> CorrelationResult:
    if not candidates:
        return CorrelationResult(
            state=MatchState.POSSIBLE_MATCH,
            selected_id=None,
            score=0.0,
            reasons=("Aucun candidat disponible pour le rapprochement.",),
        )
    ranked = sorted(candidates, key=lambda item: (-item[1], item[0]))
    top_score = ranked[0][1]
    tied = [item for item in ranked if abs(item[1] - top_score) < 1e-9]
    if len(tied) > 1:
        return CorrelationResult(
            state=MatchState.LIKELY_MATCH if top_score >= 0.55 else MatchState.POSSIBLE_MATCH,
            selected_id=None,
            score=top_score,
            reasons=(
                "Plusieurs candidats ont exactement le même niveau de preuve; aucun lien n'est confirmé automatiquement.",
            ),
            ambiguous_ids=tuple(item[0] for item in tied),
        )
    identifier, score, reasons = ranked[0]
    state = _state_for_score(score)
    return CorrelationResult(
        state=state,
        selected_id=identifier if score >= 0.55 else None,
        score=score,
        reasons=reasons or ("Preuves de rapprochement faibles.",),
    )


def correlate_order(
    transaction: BankTransaction,
    candidates: tuple[OrderEvidence, ...] | list[OrderEvidence],
) -> CorrelationResult:
    scored = [
        (
            candidate.order_id,
            *_score_evidence(
                transaction,
                amount=candidate.amount,
                currency=candidate.currency,
                merchant=candidate.merchant,
                event_date=candidate.event_date,
                reference=candidate.reference,
            ),
        )
        for candidate in candidates
    ]
    return _rank_candidates(scored)


def correlate_invoice(
    transaction: BankTransaction,
    candidates: tuple[InvoiceEvidence, ...] | list[InvoiceEvidence],
) -> CorrelationResult:
    scored = [
        (
            candidate.invoice_id,
            *_score_evidence(
                transaction,
                amount=candidate.amount,
                currency=candidate.currency,
                merchant=candidate.merchant,
                event_date=candidate.event_date,
                reference=candidate.reference,
            ),
        )
        for candidate in candidates
    ]
    return _rank_candidates(scored)
