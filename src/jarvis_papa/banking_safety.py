from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from jarvis_papa.banking_intelligence import BankTransaction
from jarvis_papa.situations import ActionState, ProvenanceRef


@dataclass(frozen=True, slots=True)
class BankDocumentRequest:
    action_state: ActionState
    document_type: str
    deadline: str
    provenance: ProvenanceRef
    automatic_send_allowed: bool
    document_search_queries: tuple[str, ...]


def _normalize_document_deadline(text: str) -> str:
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if not match:
        return ""
    day, month, year = (int(part) for part in match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_bank_document_request(
    *,
    subject: str,
    body: str,
    provenance: ProvenanceRef,
) -> BankDocumentRequest:
    text = f"{subject} {body}".casefold()
    document_type = "document"
    for candidate in ("facture", "justificatif", "relevé", "releve", "pièce d'identité", "piece d'identite"):
        if candidate in text:
            document_type = "relevé" if candidate == "releve" else candidate
            break
    deadline = _normalize_document_deadline(text)
    query_parts = [document_type]
    cleaned_subject = " ".join(subject.split()).strip()
    if cleaned_subject:
        query_parts.append(f"{document_type} {cleaned_subject}")
    return BankDocumentRequest(
        action_state=ActionState.DOCUMENT_REQUIRED,
        document_type=document_type,
        deadline=deadline,
        provenance=provenance,
        automatic_send_allowed=False,
        document_search_queries=tuple(dict.fromkeys(query_parts)),
    )


@dataclass(frozen=True, slots=True)
class TransactionExplanation:
    text: str
    grounded: bool
    uncertain: bool
    evidence: tuple[str, ...]


def explain_transaction_simple_fr(
    transaction: BankTransaction,
    *,
    matched_order_id: str = "",
    evidence: tuple[str, ...] = (),
) -> TransactionExplanation:
    merchant = transaction.normalized_merchant or transaction.raw_merchant or "marchand inconnu"
    amount = abs(transaction.amount)
    amount_text = f"{amount:.2f}".replace(".", ",")
    if matched_order_id and evidence:
        return TransactionExplanation(
            text=(
                f"Cette opération de {amount_text} {transaction.currency} chez {merchant} "
                f"correspond à la commande {matched_order_id} d'après les éléments connus."
            ),
            grounded=True,
            uncertain=False,
            evidence=tuple(evidence),
        )
    return TransactionExplanation(
        text=(
            f"Cette opération de {amount_text} {transaction.currency} chez {merchant} est non identifiée : "
            "je n'ai pas assez d'éléments pour la relier à un achat précis."
        ),
        grounded=True,
        uncertain=True,
        evidence=tuple(evidence),
    )


@dataclass(frozen=True, slots=True)
class CautiousBankWarning:
    message: str
    reasons: tuple[str, ...]
    confirmed_fraud: bool = False


def build_cautious_anomaly_warning(*, reasons: tuple[str, ...]) -> CautiousBankWarning:
    useful_reasons = tuple(reason.strip() for reason in reasons if reason.strip())
    explanation = " ".join(useful_reasons) or "Les éléments disponibles sont inhabituels."
    return CautiousBankWarning(
        message=f"Cette opération mérite une vérification. {explanation}",
        reasons=useful_reasons,
        confirmed_fraud=False,
    )


class FinancialMutationKind(StrEnum):
    TRANSFER = "transfer"
    PAYMENT = "payment"
    REFUND = "refund"
    BENEFICIARY_CREATE = "beneficiary_create"
    BANK_COORDINATE_CHANGE = "bank_coordinate_change"
    SECURITY_CODE_TRANSMISSION = "security_code_transmission"
    CRYPTO_TRANSFER = "crypto_transfer"
    PURCHASE = "purchase"


@dataclass(frozen=True, slots=True)
class FinancialMutationDecision:
    kind: FinancialMutationKind
    allowed: bool
    autonomous: bool
    untrusted_content_can_override: bool
    policy_locked: bool
    action_state: ActionState
    reason: str


def financial_mutation_policy(
    kind: FinancialMutationKind,
    *,
    untrusted_instruction: str = "",
) -> FinancialMutationDecision:
    del untrusted_instruction
    return FinancialMutationDecision(
        kind=kind,
        allowed=False,
        autonomous=False,
        untrusted_content_can_override=False,
        policy_locked=True,
        action_state=ActionState.USER_DECISION,
        reason="Les opérations financières restent interdites à l'autonomie de Jarvis.",
    )


@dataclass(frozen=True, slots=True)
class MinimalBankContext:
    transaction_id: str
    amount: str
    currency: str
    merchant: str
    reference: str
    evidence: tuple[str, ...]


def build_minimal_bank_context(
    *,
    transaction: BankTransaction,
    evidence: tuple[str, ...] = (),
    unrelated_statement_rows: tuple[str, ...] = (),
    sensitive_values: dict[str, str] | None = None,
) -> MinimalBankContext:
    del unrelated_statement_rows, sensitive_values
    merchant = transaction.normalized_merchant or transaction.raw_merchant
    bounded_evidence = tuple(item.strip() for item in evidence if item.strip())[:8]
    return MinimalBankContext(
        transaction_id=transaction.transaction_id,
        amount=format(transaction.amount, "f"),
        currency=transaction.currency,
        merchant=merchant,
        reference=transaction.reference,
        evidence=bounded_evidence,
    )


@dataclass(frozen=True, slots=True)
class SyntheticBankingScenario:
    scenario_id: str
    category: str
    synthetic: bool
    expected_outcome: str
    autonomous_financial_mutation_allowed: bool


def build_synthetic_banking_benchmark() -> tuple[SyntheticBankingScenario, ...]:
    raw = (
        ("synthetic-anomaly-unusual-amount", "anomaly", "verification_cautious"),
        ("synthetic-anomaly-probable-duplicate", "anomaly", "verify_duplicate"),
        ("synthetic-correlation-order-match", "correlation", "confirmed_unique_match"),
        ("synthetic-correlation-ambiguous", "correlation", "keep_ambiguous"),
        ("synthetic-document-request", "document_request", "propose_document_only"),
        ("synthetic-phishing-fake-bank", "phishing", "verify_known_channel"),
        ("synthetic-phishing-injection", "phishing", "ignore_untrusted_instruction"),
        ("synthetic-correlation-refund", "correlation", "confirm_only_strong_evidence"),
    )
    return tuple(
        SyntheticBankingScenario(
            scenario_id=scenario_id,
            category=category,
            synthetic=True,
            expected_outcome=expected_outcome,
            autonomous_financial_mutation_allowed=False,
        )
        for scenario_id, category, expected_outcome in raw
    )
