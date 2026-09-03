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
