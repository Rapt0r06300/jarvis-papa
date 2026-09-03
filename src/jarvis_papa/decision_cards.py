from __future__ import annotations

from dataclasses import dataclass


_FORBIDDEN_PRIMARY_TERMS = (
    "fastapi",
    "json",
    "port",
    "ollama",
    "qwen",
    "traceback",
    "stack trace",
)


@dataclass(frozen=True)
class CopyAudit:
    text: str
    allowed: bool
    forbidden_terms: tuple[str, ...]


def audit_robert_copy(text: str, *, diagnostic: bool = False) -> CopyAudit:
    if diagnostic:
        return CopyAudit(text=text, allowed=True, forbidden_terms=())
    lowered = text.casefold()
    found = tuple(term for term in _FORBIDDEN_PRIMARY_TERMS if term in lowered)
    return CopyAudit(text=text, allowed=not found, forbidden_terms=found)


@dataclass(frozen=True)
class DecisionCard:
    title: str
    recommendation: str
    reason: str
    alternatives: tuple[str, ...] = ()
    has_more: bool = False
    actions: tuple[str, ...] = ()
    body: str = ""
    source_context: str | None = None
    external_send_allowed: bool = False


def build_decision_card(
    *,
    title: str,
    recommendation: str,
    reason: str,
    alternatives: tuple[str, ...] = (),
) -> DecisionCard:
    visible = tuple(alternatives[:2])
    return DecisionCard(
        title=title,
        recommendation=recommendation,
        reason=reason,
        alternatives=visible,
        has_more=len(alternatives) > len(visible),
    )


@dataclass(frozen=True)
class ParcelEvidence:
    parcel_name: str
    status: str
    deadline: str
    pickup_code: str | None = None
    qr_payload: str | None = None
    source_mail_id: str | None = None


def build_parcel_card(evidence: ParcelEvidence) -> DecisionCard:
    actions: list[str] = []
    if evidence.pickup_code:
        actions.append("Afficher le code")
    if evidence.qr_payload:
        actions.append("Afficher le QR")
    if evidence.source_mail_id:
        actions.append("Ouvrir le mail")
    actions.append("Me le rappeler demain")
    return DecisionCard(
        title=evidence.parcel_name,
        recommendation=evidence.status,
        reason=f"Échéance de retrait : {evidence.deadline}.",
        actions=tuple(actions),
        source_context=evidence.source_mail_id,
    )


@dataclass(frozen=True)
class MarketplaceEvidence:
    item: str
    asking_price: float
    buyer_offer: float
    conversation_id: str


def _format_euros(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)} €"
    return f"{value:.2f} €".replace(".", ",")


def build_marketplace_card(evidence: MarketplaceEvidence) -> DecisionCard:
    midpoint = (evidence.asking_price + evidence.buyer_offer) / 2
    recommendation = f"Proposer {_format_euros(midpoint)}"
    return DecisionCard(
        title=f"{evidence.item} — offre acheteur",
        recommendation=recommendation,
        reason=(
            f"Prix demandé {_format_euros(evidence.asking_price)}, "
            f"offre reçue {_format_euros(evidence.buyer_offer)}."
        ),
        alternatives=(
            f"Accepter {_format_euros(evidence.buyer_offer)}",
            "Refuser l’offre",
        ),
        actions=("Ouvrir la conversation",),
        source_context=evidence.conversation_id,
        external_send_allowed=False,
    )


@dataclass(frozen=True)
class BankReviewEvidence:
    merchant: str
    amount: float
    explanation: str | None
    confidence: float
    unusual: bool = False


def build_bank_review_card(evidence: BankReviewEvidence) -> DecisionCard:
    if evidence.explanation:
        body = evidence.explanation
    elif evidence.unusual:
        body = (
            "Cette opération inhabituelle n’est pas expliquée avec assez de certitude. "
            "Il est utile de la vérifier à partir du relevé et des justificatifs disponibles."
        )
    else:
        body = "Cette opération peut être revue avec les éléments disponibles."
    return DecisionCard(
        title=f"Opération {evidence.merchant}",
        recommendation="Vérifier les éléments disponibles",
        reason=f"Niveau de confiance : {max(0.0, min(1.0, evidence.confidence)):.0%}.",
        actions=("Ouvrir le relevé", "Voir les éléments liés"),
        body=body,
        external_send_allowed=False,
    )
