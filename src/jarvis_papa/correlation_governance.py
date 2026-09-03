from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from .situations import ProvenanceRef


_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "cvv",
    "pin",
    "otp",
    "otp_code",
    "2fa",
    "2fa_code",
    "sms_code",
    "code_sms",
    "confirmation_code",
    "validation_code",
}


def _norm(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _sanitize_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    if not metadata:
        return {}
    clean: dict[str, str] = {}
    for key, value in metadata.items():
        normalized_key = key.casefold().strip()
        if normalized_key in _SECRET_KEYS:
            continue
        clean[str(key)] = str(value)[:500]
    return clean


@dataclass(frozen=True, slots=True)
class MarketplaceConversation:
    platform: str
    conversation_id: str
    listing_id: str
    item_name: str
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True, slots=True)
class MarketplaceListing:
    platform: str
    listing_id: str
    item_name: str
    item_id: str
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True, slots=True)
class MarketplaceListingLink:
    confirmed: bool
    listing_id: str
    item_id: str
    confidence: float
    reasons: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]


def link_marketplace_conversation(
    conversation: MarketplaceConversation,
    listings: tuple[MarketplaceListing, ...],
) -> MarketplaceListingLink:
    exact = [
        listing
        for listing in listings
        if _norm(listing.platform) == _norm(conversation.platform)
        and conversation.listing_id
        and _norm(listing.listing_id) == _norm(conversation.listing_id)
    ]
    if len(exact) == 1:
        listing = exact[0]
        return MarketplaceListingLink(
            True,
            listing.listing_id,
            listing.item_id,
            0.99,
            ("platform_listing_id",),
            (*conversation.provenance, *listing.provenance),
        )

    name_matches = [
        listing
        for listing in listings
        if _norm(listing.platform) == _norm(conversation.platform)
        and conversation.item_name
        and _norm(listing.item_name) == _norm(conversation.item_name)
    ]
    if len(name_matches) == 1:
        listing = name_matches[0]
        return MarketplaceListingLink(
            False,
            listing.listing_id,
            listing.item_id,
            0.55,
            ("item_name",),
            (*conversation.provenance, *listing.provenance),
        )
    return MarketplaceListingLink(False, "", "", 0.0, (), conversation.provenance)


class RelationReviewDecision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RelationRecord:
    relation_id: str
    source_entity_ids: tuple[str, ...]
    evidence_version: str
    active: bool
    user_label: str = ""
    provenance: tuple[ProvenanceRef, ...] = ()
    rejected_evidence_version: str = ""


@dataclass(frozen=True, slots=True)
class RelationAuditEvent:
    action: str
    relation_id: str
    evidence_version: str
    actor: str
    metadata: dict[str, str]
    provenance: tuple[ProvenanceRef, ...]


class RelationStore:
    def __init__(self) -> None:
        self._relations: dict[str, RelationRecord] = {}
        self._audit: list[RelationAuditEvent] = []
        self.source_entity_ids: set[str] = set()

    def _record(
        self,
        action: str,
        relation: RelationRecord,
        *,
        actor: str,
        provenance: ProvenanceRef | tuple[ProvenanceRef, ...],
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        refs = provenance if isinstance(provenance, tuple) else (provenance,)
        self._audit.append(
            RelationAuditEvent(
                action=action,
                relation_id=relation.relation_id,
                evidence_version=relation.evidence_version,
                actor=actor,
                metadata=_sanitize_metadata(metadata),
                provenance=refs,
            )
        )

    def merge(
        self,
        relation_id: str,
        source_entity_ids: tuple[str, ...],
        *,
        evidence_version: str,
        provenance: tuple[ProvenanceRef, ...],
    ) -> RelationRecord:
        entities = tuple(sorted(set(source_entity_ids)))
        self.source_entity_ids.update(entities)
        relation = RelationRecord(relation_id, entities, evidence_version, True, provenance=provenance)
        self._relations[relation_id] = relation
        self._record("merge", relation, actor="engine", provenance=provenance)
        return relation

    def propose(
        self,
        relation_id: str,
        source_entity_ids: tuple[str, ...],
        *,
        evidence_version: str,
        provenance: tuple[ProvenanceRef, ...],
    ) -> RelationRecord:
        entities = tuple(sorted(set(source_entity_ids)))
        self.source_entity_ids.update(entities)
        relation = RelationRecord(relation_id, entities, evidence_version, False, provenance=provenance)
        self._relations[relation_id] = relation
        self._record("propose", relation, actor="engine", provenance=provenance)
        return relation

    def split(self, relation_id: str, *, actor: str, provenance: ProvenanceRef) -> RelationRecord:
        relation = replace(self.get(relation_id), active=False)
        self._relations[relation_id] = relation
        self._record("split", relation, actor=actor, provenance=provenance)
        return relation

    def restore(self, relation_id: str, *, actor: str, provenance: ProvenanceRef) -> RelationRecord:
        relation = replace(self.get(relation_id), active=True)
        self._relations[relation_id] = relation
        self._record("restore", relation, actor=actor, provenance=provenance)
        return relation

    def review(
        self,
        relation_id: str,
        decision: RelationReviewDecision,
        *,
        actor: str,
        provenance: ProvenanceRef,
        metadata: Mapping[str, str] | None = None,
    ) -> RelationRecord:
        current = self.get(relation_id)
        if decision is RelationReviewDecision.CONFIRM:
            relation = replace(
                current,
                active=True,
                user_label="Oui, c’est la même commande",
                provenance=(*current.provenance, provenance),
                rejected_evidence_version="",
            )
            action = "confirm"
        else:
            relation = replace(
                current,
                active=False,
                user_label="Non",
                provenance=(*current.provenance, provenance),
                rejected_evidence_version=current.evidence_version,
            )
            action = "reject"
        self._relations[relation_id] = relation
        self._record(action, relation, actor=actor, provenance=provenance, metadata=metadata)
        return relation

    def can_auto_confirm(self, relation_id: str, *, evidence_version: str) -> bool:
        relation = self.get(relation_id)
        return not (
            relation.rejected_evidence_version
            and relation.rejected_evidence_version == evidence_version
        )

    def get(self, relation_id: str) -> RelationRecord:
        return self._relations[relation_id]

    def audit_events(self) -> tuple[RelationAuditEvent, ...]:
        return tuple(self._audit)


@dataclass(frozen=True, slots=True)
class SearchSourceResult:
    result_type: str
    result_id: str
    title: str
    relevance: float
    source: str
    provenance: tuple[ProvenanceRef, ...]


def unified_search(query: str, results: tuple[SearchSourceResult, ...]) -> tuple[SearchSourceResult, ...]:
    terms = {_norm(term) for term in query.split() if term.strip()}

    def adjusted(result: SearchSourceResult) -> tuple[float, str, str]:
        title = _norm(result.title)
        lexical_bonus = 0.02 * sum(1 for term in terms if term and term in title)
        return (-(min(1.0, result.relevance + lexical_bonus)), result.result_type, result.result_id)

    return tuple(sorted(results, key=adjusted))
