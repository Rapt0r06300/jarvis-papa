from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from jarvis_papa.situations import ActionState, ProvenanceRef


class BankingSensitivity(StrEnum):
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


@dataclass(frozen=True, slots=True)
class BankingDataPolicy:
    field: str
    sensitivity: BankingSensitivity
    durable_memory_allowed: bool
    privileged_tool_allowed: bool


_HIGHLY_SENSITIVE_FIELDS = (
    "password",
    "passwd",
    "pin",
    "cvv",
    "cryptogram",
    "token",
    "otp",
    "2fa",
    "sms_code",
    "code_sms",
    "authentication_code",
    "confirmation_code",
    "card_number",
    "private_key",
)
_SENSITIVE_FIELDS = (
    "transaction",
    "amount",
    "balance",
    "statement",
    "iban",
    "bic",
    "account_number",
    "bank_account",
    "merchant",
    "reference",
)


def classify_banking_data(field: str, value: object = "") -> BankingDataPolicy:
    """Return an explicit retention/tool policy for a banking datum.

    The classifier intentionally keys primarily on the field role, not the value,
    so a model cannot downgrade a secret merely by rephrasing its contents.
    """

    normalized = re.sub(r"[^a-z0-9]+", "_", str(field).casefold()).strip("_")
    probe = f"{normalized} {str(value).casefold()}"
    if any(marker in normalized for marker in _HIGHLY_SENSITIVE_FIELDS) or any(
        marker in probe for marker in ("one time password", "one-time password", "code 2fa")
    ):
        return BankingDataPolicy(
            field=normalized,
            sensitivity=BankingSensitivity.HIGHLY_SENSITIVE,
            durable_memory_allowed=False,
            privileged_tool_allowed=False,
        )
    if any(marker in normalized for marker in _SENSITIVE_FIELDS):
        return BankingDataPolicy(
            field=normalized,
            sensitivity=BankingSensitivity.SENSITIVE,
            durable_memory_allowed=True,
            privileged_tool_allowed=False,
        )
    return BankingDataPolicy(
        field=normalized,
        sensitivity=BankingSensitivity.PERSONAL,
        durable_memory_allowed=True,
        privileged_tool_allowed=False,
    )


class BankAdapterHealth(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    AUTH_REQUIRED = "auth_required"
    UNAVAILABLE = "unavailable"


class BankDataAdapter:
    """Read-only banking adapter contract.

    Mutation primitives are deliberately absent from this interface. Concrete
    integrations may read/search/import data, but payments, transfers and
    beneficiary changes are outside the autonomous capability boundary.
    """

    def health(self) -> BankAdapterHealth:
        raise NotImplementedError

    def read_transactions(self) -> tuple[BankTransaction, ...]:
        raise NotImplementedError

    def import_statements(self, payload: str, *, statement_ref: str) -> ImportBankResult:
        raise NotImplementedError

    def search_transactions(self, query: str) -> tuple[BankTransaction, ...]:
        raise NotImplementedError


def bank_adapter_capabilities() -> dict[str, bool]:
    return {
        "read_transactions": True,
        "import_statements": True,
        "search_transactions": True,
        "transfer": False,
        "payment": False,
        "beneficiary_mutation": False,
    }


class BankEmailIntent(StrEnum):
    SECURITY_ALERT = "security_alert"
    DOCUMENT_REQUEST = "document_request"
    TRANSACTION_NOTICE = "transaction_notice"
    GENERAL_NOTICE = "general_notice"


class BankTrustState(StrEnum):
    TRUSTED = "trusted"
    UNKNOWN = "unknown"
    SUSPICIOUS = "suspicious"


@dataclass(frozen=True, slots=True)
class BankEmailAssessment:
    intent: BankEmailIntent
    trust_state: BankTrustState
    trust_evidence: tuple[str, ...]
    action_state: ActionState
    privileged_tools_allowed: bool
    confirmed_phishing: bool
    recommendation: str
    provenance: ProvenanceRef


_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore toutes les règles précédentes",
    "ignore toutes les regles precedentes",
    "ignore les instructions précédentes",
    "ignore les instructions precedentes",
    "system prompt",
    "jailbreak",
)
_SECRET_REQUEST_MARKERS = (
    "code sms",
    "sms code",
    "2fa",
    "otp",
    "mot de passe",
    "password",
    "code de confirmation",
    "code de validation",
)


def _domain(value: str) -> str:
    text = value.strip().casefold()
    if "@" in text and "://" not in text:
        return text.rsplit("@", 1)[-1].strip(". ")
    match = re.search(r"://([^/:?#]+)", text)
    return match.group(1).strip(". ") if match else ""


def _domain_is_trusted(domain: str, trusted_domains: tuple[str, ...]) -> bool:
    domain = domain.casefold().strip(". ")
    for trusted in trusted_domains:
        trusted = trusted.casefold().strip(". ")
        if domain == trusted or domain.endswith("." + trusted):
            return True
    return False


def assess_bank_email(
    *,
    sender: str,
    subject: str,
    body: str,
    links: tuple[str, ...] = (),
    trusted_domains: tuple[str, ...] = (),
    provenance: ProvenanceRef,
) -> BankEmailAssessment:
    text = f"{subject} {body}".casefold()
    intent = BankEmailIntent.GENERAL_NOTICE
    if any(token in text for token in ("sécurité", "securite", "bloqué", "bloque", "alerte", "fraude")):
        intent = BankEmailIntent.SECURITY_ALERT
    elif any(token in text for token in ("document", "justificatif", "pièce", "piece")):
        intent = BankEmailIntent.DOCUMENT_REQUEST
    elif any(token in text for token in ("paiement", "transaction", "débit", "debit", "crédit", "credit")):
        intent = BankEmailIntent.TRANSACTION_NOTICE

    evidence: list[str] = []
    sender_domain = _domain(sender)
    sender_trusted = bool(sender_domain and _domain_is_trusted(sender_domain, trusted_domains))
    evidence.append(
        f"domaine expéditeur {'reconnu' if sender_trusted else 'non reconnu'}: {sender_domain or 'inconnu'}"
    )

    untrusted_links = [link for link in links if not _domain_is_trusted(_domain(link), trusted_domains)]
    if links:
        evidence.append(
            "liens conformes au domaine de confiance" if not untrusted_links else "au moins un lien sort du domaine de confiance"
        )

    injection = any(marker in text for marker in _INJECTION_MARKERS)
    secret_request = any(marker in text for marker in _SECRET_REQUEST_MARKERS)
    if injection:
        evidence.append("instruction de contournement détectée dans un contenu non fiable")
    if secret_request:
        evidence.append("demande de secret/code d'authentification détectée")

    suspicious = injection or secret_request or bool(untrusted_links) or not sender_trusted
    if suspicious:
        return BankEmailAssessment(
            intent=intent,
            trust_state=BankTrustState.SUSPICIOUS,
            trust_evidence=tuple(evidence),
            action_state=ActionState.VERIFY,
            privileged_tools_allowed=False,
            confirmed_phishing=False,
            recommendation=(
                "Vérifier le message via un canal bancaire connu et indépendant. "
                "Ne transmettre aucun code, identifiant ou secret et ne valider aucune opération depuis ce message."
            ),
            provenance=provenance,
        )

    return BankEmailAssessment(
        intent=intent,
        trust_state=BankTrustState.TRUSTED if sender_trusted else BankTrustState.UNKNOWN,
        trust_evidence=tuple(evidence),
        action_state=ActionState.READ_ONLY,
        privileged_tools_allowed=False,
        confirmed_phishing=False,
        recommendation="Lire l'information sans effectuer d'opération financière autonome.",
        provenance=provenance,
    )


class BankTransactionStatus(StrEnum):
    BOOKED = "booked"
    PENDING = "pending"
    REVERSED = "reversed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BankTransaction:
    transaction_id: str
    booking_date: str
    value_date: str
    amount: Decimal
    currency: str
    raw_description: str
    raw_merchant: str
    normalized_merchant: str
    reference: str
    status: BankTransactionStatus
    provenance: tuple[ProvenanceRef, ...]
    confidence: float

    @classmethod
    def create(
        cls,
        *,
        booking_date: str,
        value_date: str,
        amount: Decimal | str | float,
        currency: str,
        raw_description: str,
        raw_merchant: str,
        normalized_merchant: str,
        reference: str,
        status: BankTransactionStatus | str,
        provenance: tuple[ProvenanceRef, ...],
        confidence: float,
    ) -> BankTransaction:
        decimal_amount = Decimal(str(amount)).normalize()
        normalized_currency = str(currency).strip().upper()
        normalized_status = status if isinstance(status, BankTransactionStatus) else BankTransactionStatus(str(status).casefold())
        stable_parts = (
            str(booking_date).strip(),
            str(value_date).strip(),
            format(decimal_amount, "f"),
            normalized_currency,
            " ".join(str(raw_description).split()),
            " ".join(str(raw_merchant).split()),
            " ".join(str(reference).split()),
            normalized_status.value,
        )
        digest = hashlib.sha256("\x1f".join(stable_parts).encode("utf-8")).hexdigest()[:32]
        return cls(
            transaction_id=digest,
            booking_date=stable_parts[0],
            value_date=stable_parts[1],
            amount=decimal_amount,
            currency=normalized_currency,
            raw_description=str(raw_description).strip(),
            raw_merchant=str(raw_merchant).strip(),
            normalized_merchant=str(normalized_merchant).strip() or str(raw_merchant).strip(),
            reference=str(reference).strip(),
            status=normalized_status,
            provenance=tuple(provenance),
            confidence=max(0.0, min(1.0, float(confidence))),
        )


@dataclass(frozen=True, slots=True)
class MerchantNormalization:
    original: str
    normalized: str
    confidence: float
    evidence: tuple[str, ...]
    matched: bool


def normalize_bank_merchant(raw_merchant: str) -> MerchantNormalization:
    original = " ".join(str(raw_merchant).split()).strip()
    folded = original.casefold()
    if re.search(r"\bamzn\b", folded) or "amazon marketplace" in folded or folded.startswith("amazon"):
        return MerchantNormalization(
            original=original,
            normalized="Amazon",
            confidence=0.96,
            evidence=("alias Amazon/AMZN reconnu avec frontière lexicale",),
            matched=True,
        )
    if "paypal" in folded:
        return MerchantNormalization(
            original=original,
            normalized="PayPal",
            confidence=0.92,
            evidence=("libellé PayPal explicite",),
            matched=True,
        )
    return MerchantNormalization(
        original=original,
        normalized=original,
        confidence=0.2 if len(original) >= 4 else 0.0,
        evidence=("aucun alias suffisamment fiable",),
        matched=False,
    )


@dataclass(frozen=True, slots=True)
class RejectedBankRow:
    row_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class ImportBankResult:
    records: tuple[BankTransaction, ...]
    rejected_rows: tuple[RejectedBankRow, ...]


def import_bank_csv(
    csv_text: str,
    *,
    statement_ref: str,
    observed_at: float,
) -> ImportBankResult:
    records: list[BankTransaction] = []
    rejected: list[RejectedBankRow] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {
        "booking_date",
        "value_date",
        "amount",
        "currency",
        "description",
        "merchant",
        "reference",
        "status",
    }
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        return ImportBankResult((), (RejectedBankRow(1, "En-têtes bancaires requis absents."),))

    seen_ids: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        try:
            amount = Decimal(str(row.get("amount") or "").strip())
            status_raw = str(row.get("status") or "unknown").strip().casefold()
            status = BankTransactionStatus(status_raw)
            merchant = normalize_bank_merchant(str(row.get("merchant") or ""))
            provenance = (
                ProvenanceRef(
                    "bank_statement_import",
                    str(statement_ref),
                    float(observed_at),
                    locator=f"csv-row:{row_number}",
                ),
            )
            transaction = BankTransaction.create(
                booking_date=str(row.get("booking_date") or ""),
                value_date=str(row.get("value_date") or ""),
                amount=amount,
                currency=str(row.get("currency") or ""),
                raw_description=str(row.get("description") or ""),
                raw_merchant=str(row.get("merchant") or ""),
                normalized_merchant=merchant.normalized,
                reference=str(row.get("reference") or ""),
                status=status,
                provenance=provenance,
                confidence=0.95 if merchant.matched else 0.8,
            )
        except (InvalidOperation, ValueError, TypeError) as exc:
            rejected.append(RejectedBankRow(row_number, f"Ligne rejetée: {type(exc).__name__}."))
            continue
        if transaction.transaction_id in seen_ids:
            continue
        seen_ids.add(transaction.transaction_id)
        records.append(transaction)
    return ImportBankResult(tuple(records), tuple(rejected))


@dataclass(frozen=True, slots=True)
class DuplicateAssessment:
    probable_duplicate: bool
    score: float
    reasons: tuple[str, ...]
    recommendation: str


def assess_probable_duplicate(left: BankTransaction, right: BankTransaction) -> DuplicateAssessment:
    score = 0.0
    reasons: list[str] = []
    if left.reference and right.reference and left.reference.casefold() == right.reference.casefold():
        score += 0.35
        reasons.append("Référence bancaire identique.")
    if left.amount == right.amount and left.currency == right.currency:
        score += 0.25
        reasons.append("Montant et devise identiques.")
    if left.booking_date == right.booking_date:
        score += 0.20
        reasons.append("Date de comptabilisation identique.")
    left_merchant = (left.normalized_merchant or left.raw_merchant).casefold()
    right_merchant = (right.normalized_merchant or right.raw_merchant).casefold()
    if left_merchant and left_merchant == right_merchant:
        score += 0.20
        reasons.append("Marchand normalisé identique.")
    score = min(1.0, score)
    probable = score >= 0.80
    recommendation = (
        "Vérifier ces deux écritures et leur justificatif avant toute conclusion."
        if probable
        else "Conserver les deux écritures distinctes tant que les éléments ne concordent pas davantage."
    )
    return DuplicateAssessment(
        probable_duplicate=probable,
        score=score,
        reasons=tuple(reasons),
        recommendation=recommendation,
    )
