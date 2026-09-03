from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from email.utils import parseaddr
from enum import StrEnum

from jarvis_papa.email_intelligence import EmailMessage
from jarvis_papa.situations import (
    ActionState,
    MatchState,
    NormalizedEvent,
    ProvenanceRef,
    SourceConnectionState,
    SourceHealth,
)


class MarketplacePlatform(StrEnum):
    EBAY = "ebay"
    LEBONCOIN = "leboncoin"


class MarketplaceReadCapability(StrEnum):
    HEALTH = "health"
    SYNC = "sync"
    SEARCH = "search"
    ENTITY_LOOKUP = "entity_lookup"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    SOLD = "sold"
    ENDED = "ended"
    INACTIVE = "inactive"


class MarketplaceIntent(StrEnum):
    BUYER_QUESTION = "buyer_question"
    OFFER = "offer"
    SALE = "sale"
    PAYMENT = "payment"
    SHIPPING = "shipping"
    COMPLETION = "completion"
    AVAILABILITY = "availability"
    APPOINTMENT = "appointment"
    UNKNOWN = "unknown"


class BuyerQuestionKind(StrEnum):
    AVAILABILITY = "availability"
    CONDITION = "condition"
    SPECS = "specs"
    DELIVERY = "delivery"
    HANDOFF = "handoff"
    PRICE = "price"
    DOCUMENT = "document"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class MarketplaceReadResult:
    state: SourceConnectionState
    listings: tuple[MarketplaceListing, ...] = ()
    events: tuple[NormalizedEvent, ...] = ()
    detail: str = ""
    fabricated: bool = False

    def __post_init__(self) -> None:
        if self.fabricated:
            raise ValueError("marketplace read results may never contain fabricated data")
        object.__setattr__(self, "listings", tuple(self.listings))
        object.__setattr__(self, "events", tuple(self.events))


class MarketplaceReadAdapter:
    """Read-only marketplace boundary; mutations live behind governed actions."""

    READ_CAPABILITIES = (
        MarketplaceReadCapability.HEALTH,
        MarketplaceReadCapability.SYNC,
        MarketplaceReadCapability.SEARCH,
        MarketplaceReadCapability.ENTITY_LOOKUP,
    )

    def __init__(
        self,
        platform: MarketplacePlatform,
        *,
        state: SourceConnectionState = SourceConnectionState.DISCONNECTED,
        detail: str = "",
    ) -> None:
        self.platform = MarketplacePlatform(platform)
        self.state = SourceConnectionState(state)
        self.detail = _clean_text(detail, 500)

    @property
    def read_capabilities(self) -> tuple[MarketplaceReadCapability, ...]:
        return self.READ_CAPABILITIES

    @property
    def mutation_capabilities(self) -> tuple[()]:
        return ()

    def health(self) -> SourceHealth:
        return SourceHealth(
            source=f"marketplace:{self.platform.value}",
            state=self.state,
            checked_at=time.time(),
            detail=self.detail,
        )

    def sync(self) -> MarketplaceReadResult:
        return MarketplaceReadResult(self.state, detail=self.detail)

    def search(self, query: str) -> MarketplaceReadResult:
        _ = _clean_text(query, 500)
        return MarketplaceReadResult(self.state, detail=self.detail)


@dataclass(frozen=True, slots=True)
class MarketplacePrice:
    amount: float
    currency: str
    confidence: float
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        amount = float(self.amount)
        confidence = float(self.confidence)
        currency = _clean_identifier(self.currency.upper(), 8)
        if amount < 0:
            raise ValueError("marketplace price must be non-negative")
        if not currency:
            raise ValueError("marketplace price requires a currency")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("marketplace price confidence must be between 0 and 1")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "provenance", tuple(self.provenance)[:16])

    def to_dict(self) -> dict[str, object]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "confidence": self.confidence,
            "provenance": [item.to_dict() for item in self.provenance],
        }


@dataclass(frozen=True, slots=True)
class MarketplaceListing:
    listing_id: str
    platform: MarketplacePlatform
    title: str
    price: MarketplacePrice
    description: str
    status: ListingStatus
    item_refs: tuple[str, ...] = ()
    photo_refs: tuple[str, ...] = ()
    document_refs: tuple[str, ...] = ()
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        listing_id = _clean_identifier(self.listing_id, 240)
        if not listing_id:
            raise ValueError("marketplace listing requires listing_id")
        object.__setattr__(self, "listing_id", listing_id)
        object.__setattr__(self, "platform", MarketplacePlatform(self.platform))
        object.__setattr__(self, "title", _clean_text(self.title, 500))
        object.__setattr__(self, "description", _clean_text(self.description, 4000))
        object.__setattr__(self, "status", ListingStatus(self.status))
        object.__setattr__(self, "item_refs", _clean_refs(self.item_refs))
        object.__setattr__(self, "photo_refs", _clean_refs(self.photo_refs))
        object.__setattr__(self, "document_refs", _clean_refs(self.document_refs))
        object.__setattr__(self, "provenance", tuple(self.provenance)[:16])

    def to_dict(self) -> dict[str, object]:
        return {
            "listing_id": self.listing_id,
            "platform": self.platform.value,
            "title": self.title,
            "price": self.price.to_dict(),
            "description": self.description,
            "status": self.status.value,
            "item_refs": list(self.item_refs),
            "photo_refs": list(self.photo_refs),
            "document_refs": list(self.document_refs),
            "provenance": [item.to_dict() for item in self.provenance],
        }

    def to_situation_metadata(self) -> dict[str, object]:
        """Expose only generic facts understood by the canonical situation layer."""
        return {
            "listing_id": self.listing_id,
            "marketplace_platform": self.platform.value,
            "listing_title": self.title,
            "listing_status": self.status.value,
            "asking_price": self.price.amount,
            "currency": self.price.currency,
            "item_refs": list(self.item_refs),
        }


@dataclass(frozen=True, slots=True)
class MarketplaceIdentity:
    platform: MarketplacePlatform
    native_id: str
    display_name: str
    aliases: tuple[str, ...] = ()
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        native_id = _clean_identifier(self.native_id, 240)
        if not native_id:
            raise ValueError("marketplace identity requires native_id")
        object.__setattr__(self, "platform", MarketplacePlatform(self.platform))
        object.__setattr__(self, "native_id", native_id)
        object.__setattr__(self, "display_name", _clean_text(self.display_name, 300))
        object.__setattr__(self, "aliases", _clean_refs(self.aliases))
        object.__setattr__(self, "provenance", tuple(self.provenance)[:16])

    @property
    def identity_key(self) -> str:
        material = f"{self.platform.value}|{self.native_id.casefold()}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MarketplaceIdentityLink:
    state: MatchState
    confidence: float
    evidence: tuple[str, ...] = ()


def assess_marketplace_identity_link(
    left: MarketplaceIdentity,
    right: MarketplaceIdentity,
    *,
    confidence: float,
    evidence: tuple[str, ...] = (),
) -> MarketplaceIdentityLink:
    score = max(0.0, min(float(confidence), 1.0))
    clean_evidence = _clean_refs(evidence)
    if left.platform is right.platform and left.native_id == right.native_id:
        return MarketplaceIdentityLink(MatchState.CONFIRMED_MATCH, max(score, 0.99), clean_evidence)
    if score >= 0.8 and clean_evidence:
        return MarketplaceIdentityLink(MatchState.CONFIRMED_MATCH, score, clean_evidence)
    if score >= 0.55 and clean_evidence:
        return MarketplaceIdentityLink(MatchState.LIKELY_MATCH, score, clean_evidence)
    return MarketplaceIdentityLink(MatchState.POSSIBLE_MATCH, score, clean_evidence)


@dataclass(frozen=True, slots=True)
class MarketplaceParseResult:
    platform: MarketplacePlatform
    intent: MarketplaceIntent
    event: NormalizedEvent | None
    confidence: float
    uncertain: bool
    reasons: tuple[str, ...] = ()


class EbayMessageParser:
    SOURCE_VERSION = "marketplace-ebay-email-v1"
    supports_direct_integration = False

    def parse(self, message: EmailMessage) -> MarketplaceParseResult:
        if not _trusted_sender_domain(message.sender, ("ebay.fr", "ebay.com")):
            return MarketplaceParseResult(
                MarketplacePlatform.EBAY,
                MarketplaceIntent.UNKNOWN,
                None,
                0.2,
                True,
                ("untrusted_sender",),
            )
        return _parse_marketplace_email(
            message,
            platform=MarketplacePlatform.EBAY,
            source="ebay_email",
            source_version=self.SOURCE_VERSION,
        )


class LeboncoinMessageParser:
    SOURCE_VERSION = "marketplace-leboncoin-email-v1"
    supports_direct_integration = False

    def parse(self, message: EmailMessage) -> MarketplaceParseResult:
        if not _trusted_sender_domain(message.sender, ("leboncoin.fr",)):
            return MarketplaceParseResult(
                MarketplacePlatform.LEBONCOIN,
                MarketplaceIntent.UNKNOWN,
                None,
                0.2,
                True,
                ("untrusted_sender",),
            )
        return _parse_marketplace_email(
            message,
            platform=MarketplacePlatform.LEBONCOIN,
            source="leboncoin_email",
            source_version=self.SOURCE_VERSION,
        )


@dataclass(frozen=True, slots=True)
class BuyerQuestion:
    kind: BuyerQuestionKind
    requested_answer: str
    action_state: ActionState
    listing_id: str
    item_refs: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]
    confidence: float
    text: str


def extract_buyer_question(
    message: EmailMessage,
    *,
    platform: MarketplacePlatform,
    listing: MarketplaceListing | None = None,
) -> BuyerQuestion | None:
    _ = MarketplacePlatform(platform)
    text = f"{message.subject}\n{message.body}"
    folded = text.casefold()
    kind, requested = _question_kind(folded)
    looks_like_question = "?" in text or any(
        marker in folded
        for marker in ("est-ce", "est ce", "pouvez-vous", "pouvez vous", "disponible")
    )
    if kind is BuyerQuestionKind.OTHER and not looks_like_question:
        return None
    listing_id = listing.listing_id if listing is not None else ""
    item_refs = listing.item_refs if listing is not None else ()
    provenance = [message.provenance]
    if listing is not None:
        provenance.extend(listing.provenance)
    return BuyerQuestion(
        kind=kind,
        requested_answer=requested,
        action_state=ActionState.REPLY,
        listing_id=listing_id,
        item_refs=item_refs,
        provenance=tuple(dict.fromkeys(provenance))[:16],
        confidence=0.94 if kind is not BuyerQuestionKind.OTHER else 0.7,
        text=_clean_text(message.body, 2000),
    )


@dataclass(frozen=True, slots=True)
class NegotiationOffer:
    offered_amount: float
    asking_amount: float | None
    currency: str
    conditions: str
    confidence: float
    provenance: tuple[ProvenanceRef, ...]


_OFFER_RE = re.compile(
    r"(?:je\s+vous\s+propose|vous\s+propose|proposition\s+(?:de\s+)?|offre\s+(?:de\s+)?)"
    r"\s*(\d+(?:[,.]\d{1,2})?)\s*(€|eur\b|euros?\b)",
    re.IGNORECASE,
)


def extract_negotiation_offer(
    text: str,
    *,
    listing: MarketplaceListing | None,
    provenance: ProvenanceRef,
) -> NegotiationOffer | None:
    clean = _clean_text(text, 4000)
    match = _OFFER_RE.search(clean)
    if match is None:
        return None
    amount = float(match.group(1).replace(",", "."))
    currency = "EUR"
    asking = listing.price.amount if listing is not None else None
    chain = [provenance]
    if listing is not None:
        chain.extend(listing.price.provenance)
        chain.extend(listing.provenance)
    conditions = clean[match.end() :].strip(" .,-;:")
    return NegotiationOffer(
        offered_amount=amount,
        asking_amount=asking,
        currency=currency,
        conditions=conditions,
        confidence=0.96,
        provenance=tuple(dict.fromkeys(chain))[:16],
    )


def _parse_marketplace_email(
    message: EmailMessage,
    *,
    platform: MarketplacePlatform,
    source: str,
    source_version: str,
) -> MarketplaceParseResult:
    text = f"{message.subject}\n{message.body}"
    folded = text.casefold()
    intent = _detect_intent(text, folded)
    if intent is MarketplaceIntent.UNKNOWN:
        return MarketplaceParseResult(
            platform,
            intent,
            None,
            0.45,
            True,
            ("unrecognized_marketplace_message",),
        )
    listing_id = _listing_id(text, platform)
    refs = (f"listing:{listing_id}",) if listing_id else ()
    event = NormalizedEvent(
        source=source,
        source_event_id=message.message_id,
        event_type=f"marketplace_{intent.value}",
        occurred_at=message.received_at,
        observed_at=message.received_at,
        subject_refs=refs,
        payload_summary=_event_summary(platform, intent, listing_id),
        provenance=(message.provenance,),
        confidence=0.95,
        source_version=source_version,
    )
    return MarketplaceParseResult(platform, intent, event, 0.95, False)


def _detect_intent(text: str, folded: str) -> MarketplaceIntent:
    if _OFFER_RE.search(text):
        return MarketplaceIntent.OFFER
    if "question" in folded or "?" in text:
        return MarketplaceIntent.BUYER_QUESTION
    if any(term in folded for term in ("paiement reçu", "payment received", "a payé")):
        return MarketplaceIntent.PAYMENT
    if any(term in folded for term in ("à expédier", "a expedier", "expédition", "expedition")):
        return MarketplaceIntent.SHIPPING
    if any(term in folded for term in ("vente terminée", "vente terminee", "transaction terminée")):
        return MarketplaceIntent.COMPLETION
    if re.search(r"\b(?:vendu|acheté|achete)\b", folded):
        return MarketplaceIntent.SALE
    if any(term in folded for term in ("rendez-vous", "rendez vous", "rdv")):
        return MarketplaceIntent.APPOINTMENT
    if any(term in folded for term in ("disponible ?", "est disponible", "toujours disponible")):
        return MarketplaceIntent.AVAILABILITY
    return MarketplaceIntent.UNKNOWN


def _question_kind(folded: str) -> tuple[BuyerQuestionKind, str]:
    if any(term in folded for term in ("livr", "expédi", "expedi", "envoi", "main propre")):
        return BuyerQuestionKind.DELIVERY, "delivery"
    if "disponib" in folded:
        return BuyerQuestionKind.AVAILABILITY, "availability"
    if any(term in folded for term in ("état", "etat", "rayure", "défaut", "defaut")):
        return BuyerQuestionKind.CONDITION, "condition"
    if any(term in folded for term in ("dimension", "taille", "modèle", "modele", "référence")):
        return BuyerQuestionKind.SPECS, "specs"
    if any(term in folded for term in ("prix", "tarif", "négoci", "negoci")):
        return BuyerQuestionKind.PRICE, "price"
    if any(term in folded for term in ("facture", "document", "preuve d'achat")):
        return BuyerQuestionKind.DOCUMENT, "document"
    if any(term in folded for term in ("rendez-vous", "rendez vous", "remise", "retrait")):
        return BuyerQuestionKind.HANDOFF, "handoff"
    return BuyerQuestionKind.OTHER, "reply"


def _listing_id(text: str, platform: MarketplacePlatform) -> str:
    if platform is MarketplacePlatform.EBAY:
        match = re.search(r"\b(?:objet|item)\s*[:#-]?\s*(\d{9,18})\b", text, re.IGNORECASE)
    else:
        match = re.search(r"\bannonce\s*[:#-]?\s*(\d{6,18})\b", text, re.IGNORECASE)
    return match.group(1) if match is not None else ""


def _event_summary(
    platform: MarketplacePlatform,
    intent: MarketplaceIntent,
    listing_id: str,
) -> str:
    labels = {
        MarketplaceIntent.BUYER_QUESTION: "Question acheteur",
        MarketplaceIntent.OFFER: "Offre acheteur",
        MarketplaceIntent.SALE: "Vente signalée",
        MarketplaceIntent.PAYMENT: "Paiement signalé",
        MarketplaceIntent.SHIPPING: "Expédition requise",
        MarketplaceIntent.COMPLETION: "Vente terminée",
        MarketplaceIntent.AVAILABILITY: "Question de disponibilité",
        MarketplaceIntent.APPOINTMENT: "Proposition de rendez-vous",
    }
    label = labels.get(intent, "Événement marketplace")
    suffix = f" · annonce {listing_id}" if listing_id else ""
    return f"{platform.value} · {label}{suffix}"


def _trusted_sender_domain(sender: str, allowed: tuple[str, ...]) -> bool:
    address = parseaddr(sender)[1].casefold().strip()
    if "@" not in address:
        return False
    domain = address.rsplit("@", 1)[1].rstrip(".")
    return any(domain == item or domain.endswith(f".{item}") for item in allowed)


def _clean_refs(values: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    for value in values:
        clean = _clean_text(value, 500)
        if clean and clean not in output:
            output.append(clean)
    return tuple(output[:32])


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value).split()).strip()[:limit]


def _clean_identifier(value: object, limit: int) -> str:
    return re.sub(r"[^A-Za-z0-9_.:@/-]+", "-", str(value).strip())[:limit]


class AskingPriceState(StrEnum):
    VERIFIED = "verified"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GroundedAskingPrice:
    amount: float | None
    currency: str | None
    state: AskingPriceState
    provenance: tuple[ProvenanceRef, ...]
    reason: str
    guessed: bool = False

    def __post_init__(self) -> None:
        if self.guessed:
            raise ValueError("marketplace asking prices may never be guessed")
        state = AskingPriceState(self.state)
        amount = None if self.amount is None else float(self.amount)
        currency = None if self.currency is None else _clean_identifier(self.currency.upper(), 8)
        if amount is not None and amount < 0:
            raise ValueError("asking price must be non-negative")
        if state is AskingPriceState.UNKNOWN and amount is not None:
            raise ValueError("unknown asking price cannot contain an amount")
        if amount is not None and not currency:
            raise ValueError("known asking price requires a currency")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:16])
        object.__setattr__(self, "reason", _clean_text(self.reason, 600))
        object.__setattr__(self, "guessed", False)


def ground_asking_price(
    listing: MarketplaceListing | None,
    *,
    now: float | None = None,
    max_age_seconds: float = 900.0,
) -> GroundedAskingPrice:
    if listing is None:
        return GroundedAskingPrice(
            None,
            None,
            AskingPriceState.UNKNOWN,
            (),
            "Prix inconnu : aucune annonce accessible ne permet de le vérifier.",
        )
    max_age = max(0.0, float(max_age_seconds))
    observed_at = max(
        (item.observed_at for item in (*listing.price.provenance, *listing.provenance)),
        default=0.0,
    )
    current_time = float(now if now is not None else time.time())
    provenance = tuple(dict.fromkeys((*listing.price.provenance, *listing.provenance)))[:16]
    if not provenance or observed_at <= 0:
        return GroundedAskingPrice(
            listing.price.amount,
            listing.price.currency,
            AskingPriceState.STALE,
            provenance,
            "Prix ancien/non vérifiable : la source datée est absente.",
        )
    age = max(0.0, current_time - observed_at)
    if age > max_age:
        return GroundedAskingPrice(
            listing.price.amount,
            listing.price.currency,
            AskingPriceState.STALE,
            provenance,
            f"Prix ancien (stale) : dernière preuve observée il y a {int(age)} s.",
        )
    return GroundedAskingPrice(
        listing.price.amount,
        listing.price.currency,
        AskingPriceState.VERIFIED,
        provenance,
        "Prix courant vérifié à partir de la preuve de l'annonce.",
    )


class NegotiationDecision(StrEnum):
    ACCEPT = "accept"
    COUNTER = "counter"
    REFUSE = "refuse"
    NEEDS_PRICE = "needs_price"


@dataclass(frozen=True, slots=True)
class NegotiationPolicy:
    counter_ratio: float = 0.90
    accept_ratio: float = 0.95
    refuse_below_ratio: float = 0.60

    def __post_init__(self) -> None:
        counter = float(self.counter_ratio)
        accept = float(self.accept_ratio)
        refuse = float(self.refuse_below_ratio)
        if not (0.0 <= refuse <= counter <= accept <= 1.0):
            raise ValueError("negotiation ratios must satisfy refuse <= counter <= accept <= 1")
        object.__setattr__(self, "counter_ratio", counter)
        object.__setattr__(self, "accept_ratio", accept)
        object.__setattr__(self, "refuse_below_ratio", refuse)


@dataclass(frozen=True, slots=True)
class NegotiationRecommendation:
    decision: NegotiationDecision
    proposed_amount: float | None
    currency: str | None
    basis: str
    action_state: ActionState
    executes_transaction: bool
    provenance: tuple[ProvenanceRef, ...]
    offer_amount: float | None = None
    asking_amount: float | None = None

    def __post_init__(self) -> None:
        if self.executes_transaction:
            raise ValueError("negotiation recommendations cannot execute transactions")
        object.__setattr__(self, "decision", NegotiationDecision(self.decision))
        object.__setattr__(self, "basis", _clean_text(self.basis, 1000))
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:16])
        object.__setattr__(self, "executes_transaction", False)


def recommend_negotiation(
    offer: NegotiationOffer,
    asking_price: GroundedAskingPrice,
    policy: NegotiationPolicy,
) -> NegotiationRecommendation:
    provenance = tuple(dict.fromkeys((*offer.provenance, *asking_price.provenance)))[:16]
    if asking_price.state is not AskingPriceState.VERIFIED or asking_price.amount is None:
        return NegotiationRecommendation(
            NegotiationDecision.NEEDS_PRICE,
            None,
            asking_price.currency or offer.currency,
            f"Aucune recommandation chiffrée : {asking_price.reason}",
            ActionState.VERIFY,
            False,
            provenance,
            offer_amount=offer.offered_amount,
            asking_amount=asking_price.amount,
        )
    asking = asking_price.amount
    ratio = offer.offered_amount / asking if asking > 0 else 1.0
    if ratio >= policy.accept_ratio:
        decision = NegotiationDecision.ACCEPT
        proposed = None
        rationale = "offre au-dessus du seuil d'acceptation"
    elif ratio < policy.refuse_below_ratio:
        decision = NegotiationDecision.REFUSE
        proposed = None
        rationale = "offre sous le seuil minimal configuré"
    else:
        decision = NegotiationDecision.COUNTER
        proposed = round(asking * policy.counter_ratio, 2)
        rationale = f"contre-proposition à {policy.counter_ratio:.0%} du prix vérifié"
    basis = (
        f"Offre {offer.offered_amount:g} {offer.currency} face au prix vérifié "
        f"de {asking:g} {asking_price.currency}; {rationale}."
    )
    return NegotiationRecommendation(
        decision,
        proposed,
        asking_price.currency,
        basis,
        ActionState.USER_DECISION,
        False,
        provenance,
        offer_amount=offer.offered_amount,
        asking_amount=asking,
    )


@dataclass(frozen=True, slots=True)
class MarketplaceReplyDraft:
    body: str
    sent: bool
    action_state: ActionState
    grounded_facts: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]

    def __post_init__(self) -> None:
        if self.sent:
            raise ValueError("marketplace reply drafts must remain unsent")
        object.__setattr__(self, "body", _clean_text(self.body, 3000))
        object.__setattr__(self, "sent", False)
        object.__setattr__(self, "grounded_facts", _clean_refs(self.grounded_facts))
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:16])


def draft_marketplace_reply(
    *,
    listing: MarketplaceListing,
    asking_price: GroundedAskingPrice,
    recommendation: NegotiationRecommendation,
) -> MarketplaceReplyDraft:
    facts = ["listing_title"]
    chain = [*listing.provenance, *asking_price.provenance, *recommendation.provenance]
    if asking_price.amount is not None:
        facts.append("asking_price")
    if (
        recommendation.decision is NegotiationDecision.COUNTER
        and recommendation.proposed_amount is not None
    ):
        facts.append("counter_price")
        amount = recommendation.proposed_amount
        currency = recommendation.currency or "EUR"
        body = f"Bonjour, pour {listing.title}, je peux vous proposer {amount:g} {currency}. Merci."
    elif recommendation.decision is NegotiationDecision.ACCEPT:
        body = f"Bonjour, votre offre pour {listing.title} me convient. Merci."
    elif recommendation.decision is NegotiationDecision.REFUSE:
        body = f"Bonjour, merci pour votre offre concernant {listing.title}, je préfère la refuser."
    else:
        body = f"Bonjour, je vérifie le prix de {listing.title} avant de vous répondre. Merci."
    return MarketplaceReplyDraft(
        body=body,
        sent=False,
        action_state=ActionState.REPLY,
        grounded_facts=tuple(facts),
        provenance=tuple(dict.fromkeys(chain))[:16],
    )


@dataclass(frozen=True, slots=True)
class MarketplaceReplyStyle:
    scope: str
    observation_count: int
    durable: bool
    concise: bool
    polite: bool
    direct: bool
    concise_confidence: float
    polite_confidence: float
    direct_confidence: float
    provenance: tuple[ProvenanceRef, ...]


class MarketplaceStyleLearner:
    """Scoped style learner that needs repeated approved replies before durability."""

    def __init__(self, *, min_observations: int = 3) -> None:
        self.min_observations = max(2, int(min_observations))
        self._observations: dict[str, list[tuple[str, ProvenanceRef]]] = {}
        self._overrides: dict[str, dict[str, bool]] = {}

    def record_approved_reply(self, scope: str, text: str, provenance: ProvenanceRef) -> None:
        clean_scope = _clean_identifier(scope, 160)
        clean_text = _clean_text(text, 3000)
        if not clean_scope or not clean_text:
            raise ValueError("style learning requires scope and approved reply text")
        self._observations.setdefault(clean_scope, []).append((clean_text, provenance))

    def inspect(self, scope: str) -> MarketplaceReplyStyle | None:
        clean_scope = _clean_identifier(scope, 160)
        observations = self._observations.get(clean_scope, [])
        if not observations:
            return None
        count = len(observations)
        concise_votes = sum(len(text) <= 160 for text, _ in observations)
        polite_votes = sum(
            any(marker in text.casefold() for marker in ("bonjour", "merci", "cordialement"))
            for text, _ in observations
        )
        direct_votes = sum(text.count(".") + text.count("!") <= 3 for text, _ in observations)
        overrides = self._overrides.get(clean_scope, {})
        concise = overrides.get("concise", concise_votes * 2 >= count)
        polite = overrides.get("polite", polite_votes * 2 >= count)
        direct = overrides.get("direct", direct_votes * 2 >= count)
        provenance = tuple(dict.fromkeys(item for _, item in observations))[:16]
        denominator = max(1, count)
        return MarketplaceReplyStyle(
            scope=clean_scope,
            observation_count=count,
            durable=count >= self.min_observations,
            concise=concise,
            polite=polite,
            direct=direct,
            concise_confidence=concise_votes / denominator,
            polite_confidence=polite_votes / denominator,
            direct_confidence=direct_votes / denominator,
            provenance=provenance,
        )

    def correct(
        self,
        scope: str,
        *,
        concise: bool | None = None,
        polite: bool | None = None,
        direct: bool | None = None,
    ) -> MarketplaceReplyStyle | None:
        clean_scope = _clean_identifier(scope, 160)
        if clean_scope not in self._observations:
            return None
        values = self._overrides.setdefault(clean_scope, {})
        for key, value in (("concise", concise), ("polite", polite), ("direct", direct)):
            if value is not None:
                values[key] = bool(value)
        return self.inspect(clean_scope)

    def forget(self, scope: str) -> None:
        clean_scope = _clean_identifier(scope, 160)
        self._observations.pop(clean_scope, None)
        self._overrides.pop(clean_scope, None)


class DeliveryMode(StrEnum):
    SHIPPING = "shipping"
    HANDOFF = "handoff"
    PICKUP = "pickup"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    mode: DeliveryMode
    action_state: ActionState
    provenance: tuple[ProvenanceRef, ...]
    text: str
    creates_transaction: bool = False

    def __post_init__(self) -> None:
        if self.creates_transaction:
            raise ValueError("delivery intent cannot create a transaction")
        object.__setattr__(self, "mode", DeliveryMode(self.mode))
        object.__setattr__(self, "text", _clean_text(self.text, 2000))
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:16])
        object.__setattr__(self, "creates_transaction", False)


def extract_delivery_intent(text: str, *, provenance: ProvenanceRef) -> DeliveryIntent:
    clean = _clean_text(text, 3000)
    folded = clean.casefold()
    if any(term in folded for term in ("mains propres", "main propre", "remise en main")):
        mode = DeliveryMode.HANDOFF
    elif any(term in folded for term in ("retrait", "venir chercher", "récupérer", "recuperer")):
        mode = DeliveryMode.PICKUP
    elif any(term in folded for term in ("livr", "expédi", "expedi", "envoi", "colis")):
        mode = DeliveryMode.SHIPPING
    else:
        mode = DeliveryMode.UNKNOWN
    action = ActionState.USER_DECISION if mode is not DeliveryMode.UNKNOWN else ActionState.VERIFY
    return DeliveryIntent(mode, action, (provenance,), clean, False)


@dataclass(frozen=True, slots=True)
class MarketplaceAppointmentProposal:
    source_text: str
    normalized_at: float | None
    timezone_name: str
    location: str | None
    needs_confirmation: bool
    action_state: ActionState
    provenance: tuple[ProvenanceRef, ...]


def extract_appointment_proposal(
    text: str,
    *,
    message_timestamp: float,
    timezone_name: str,
    provenance: ProvenanceRef,
) -> MarketplaceAppointmentProposal:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    clean = _clean_text(text, 3000)
    zone = ZoneInfo(timezone_name)
    received = datetime.fromtimestamp(float(message_timestamp), tz=zone)
    exact = re.search(r"demain\s+à\s+(\d{1,2})h(?:(\d{2}))?", clean, re.IGNORECASE)
    normalized_at: float | None = None
    source_text = ""
    location: str | None = None
    search_from = 0
    if exact is not None:
        hour = int(exact.group(1))
        minute = int(exact.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = (received + timedelta(days=1)).replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
            normalized_at = target.timestamp()
        source_text = exact.group(0)
        search_from = exact.end()
    else:
        ambiguous = re.search(
            r"demain(?:\s+en\s+fin\s+de\s+journée)?",
            clean,
            re.IGNORECASE,
        )
        if ambiguous is not None:
            source_text = ambiguous.group(0)
            search_from = ambiguous.end()
    remainder = clean[search_from:]
    location_match = re.search(
        r"\s+à\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' -]{1,80}?)(?:\s*\?|[.,;!]|$)",
        remainder,
    )
    if location_match is not None:
        location = _clean_text(location_match.group(1), 120)
    needs_confirmation = normalized_at is None or location is None
    return MarketplaceAppointmentProposal(
        source_text=source_text,
        normalized_at=normalized_at,
        timezone_name=timezone_name,
        location=location,
        needs_confirmation=needs_confirmation,
        action_state=ActionState.USER_DECISION,
        provenance=(provenance,),
    )


class SaleLifecycleState(StrEnum):
    LISTED = "listed"
    NEGOTIATING = "negotiating"
    SOLD_PAYMENT_PENDING = "sold_payment_pending"
    PAID_SHIP_REQUIRED = "paid_ship_required"
    SHIPPED = "shipped"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class MarketplaceSaleLifecycle:
    listing_id: str
    state: SaleLifecycleState
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        listing_id = _clean_identifier(self.listing_id, 240)
        if not listing_id:
            raise ValueError("sale lifecycle requires listing_id")
        object.__setattr__(self, "listing_id", listing_id)
        object.__setattr__(self, "state", SaleLifecycleState(self.state))
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:32])


@dataclass(frozen=True, slots=True)
class MarketplaceLifecycleTransition:
    lifecycle: MarketplaceSaleLifecycle
    required_action: str
    action_state: ActionState
    financial_action: bool
    payment_observation_only: bool

    def __post_init__(self) -> None:
        if self.financial_action:
            raise ValueError("marketplace lifecycle cannot initiate financial actions")
        object.__setattr__(self, "required_action", _clean_identifier(self.required_action, 80))
        object.__setattr__(self, "financial_action", False)


def apply_marketplace_event(
    lifecycle: MarketplaceSaleLifecycle,
    event: NormalizedEvent,
) -> MarketplaceLifecycleTransition:
    expected_ref = f"listing:{lifecycle.listing_id}"
    listing_refs = tuple(ref for ref in event.subject_refs if ref.startswith("listing:"))
    if listing_refs and expected_ref not in listing_refs:
        return MarketplaceLifecycleTransition(
            lifecycle,
            "verify_listing",
            ActionState.VERIFY,
            False,
            event.event_type == "marketplace_payment",
        )
    transitions: dict[str, tuple[SaleLifecycleState, str, ActionState]] = {
        "marketplace_offer": (
            SaleLifecycleState.NEGOTIATING,
            "review_offer",
            ActionState.USER_DECISION,
        ),
        "marketplace_sale": (
            SaleLifecycleState.SOLD_PAYMENT_PENDING,
            "wait_for_payment",
            ActionState.WAIT_FOR_OTHER_PARTY,
        ),
        "marketplace_payment": (
            SaleLifecycleState.PAID_SHIP_REQUIRED,
            "ship_item",
            ActionState.USER_DECISION,
        ),
        "marketplace_shipping": (
            SaleLifecycleState.SHIPPED,
            "track_shipping",
            ActionState.READ_ONLY,
        ),
        "marketplace_completion": (
            SaleLifecycleState.COMPLETED,
            "",
            ActionState.NO_ACTION,
        ),
    }
    target = transitions.get(event.event_type)
    if target is None:
        return MarketplaceLifecycleTransition(
            lifecycle,
            "",
            ActionState.NO_ACTION,
            False,
            False,
        )
    next_state, required_action, action_state = target
    chain = tuple(dict.fromkeys((*lifecycle.provenance, *event.provenance)))[:32]
    updated = MarketplaceSaleLifecycle(lifecycle.listing_id, next_state, chain)
    return MarketplaceLifecycleTransition(
        updated,
        required_action,
        action_state,
        False,
        event.event_type == "marketplace_payment",
    )
