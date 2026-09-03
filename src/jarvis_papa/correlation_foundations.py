from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from jarvis_papa.situations import ProvenanceRef


@dataclass(frozen=True, slots=True)
class CorrelationEntity:
    source_kind: str
    entity_id: str
    normalized_fields: dict[str, str]
    provenance: tuple[ProvenanceRef, ...]


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    linked_entity_ids: tuple[str, ...]
    confidence: float
    evidence: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]


class CrossSourceCorrelationService:
    _STRONG_KEYS = ("order_id", "tracking_id", "invoice_id", "reference")

    def correlate(self, entities: tuple[CorrelationEntity, ...]) -> CorrelationResult:
        if not entities:
            return CorrelationResult((), 0.0, (), ())

        evidence: list[str] = []
        confidence = 0.0
        for key in self._STRONG_KEYS:
            values = [entity.normalized_fields.get(key, "").strip() for entity in entities]
            populated = [value for value in values if value]
            if len(populated) >= 2 and len(set(populated)) == 1:
                evidence.append(f"{key}={populated[0]}")
                confidence = max(confidence, 0.95)

        if not evidence:
            shared_pairs = 0
            for index, left in enumerate(entities):
                for right in entities[index + 1 :]:
                    common = {
                        key
                        for key, value in left.normalized_fields.items()
                        if value and right.normalized_fields.get(key) == value
                    }
                    shared_pairs += len(common)
            confidence = min(0.75, shared_pairs * 0.15)

        provenance: list[ProvenanceRef] = []
        seen: set[tuple[str, str, float]] = set()
        for entity in entities:
            for ref in entity.provenance:
                key = (ref.source, ref.source_id, ref.observed_at)
                if key not in seen:
                    provenance.append(ref)
                    seen.add(key)

        return CorrelationResult(
            linked_entity_ids=tuple(sorted(entity.entity_id for entity in entities)),
            confidence=confidence,
            evidence=tuple(evidence),
            provenance=tuple(provenance),
        )


class EvidenceStrength(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    key: str
    strength: EvidenceStrength
    matched: bool
    detail: str


@dataclass(frozen=True, slots=True)
class EvidenceScore:
    score: float
    strength: EvidenceStrength
    explanations: tuple[str, ...]


def score_correlation_evidence(signals: tuple[EvidenceSignal, ...]) -> EvidenceScore:
    weights = {
        EvidenceStrength.STRONG: 0.90,
        EvidenceStrength.MEDIUM: 0.45,
        EvidenceStrength.WEAK: 0.15,
    }
    matched = tuple(signal for signal in signals if signal.matched)
    if not matched:
        return EvidenceScore(0.0, EvidenceStrength.WEAK, ())

    score = min(1.0, sum(weights[signal.strength] for signal in matched))
    if any(signal.strength is EvidenceStrength.STRONG for signal in matched):
        strength = EvidenceStrength.STRONG
    elif any(signal.strength is EvidenceStrength.MEDIUM for signal in matched):
        strength = EvidenceStrength.MEDIUM
    else:
        strength = EvidenceStrength.WEAK
    explanations = tuple(f"{signal.key}: {signal.detail}" for signal in matched)
    return EvidenceScore(score, strength, explanations)


@dataclass(frozen=True, slots=True)
class MerchantAliasResolution:
    raw: str
    canonical: str
    confidence: float
    matched: bool
    provenance: ProvenanceRef | None


@dataclass(frozen=True, slots=True)
class _MerchantAliasRecord:
    canonical: str
    raw_alias: str
    confidence: float
    scope: str
    provenance: ProvenanceRef
    rejected: bool = False


class MerchantAliasRegistry:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], _MerchantAliasRecord] = {}

    @staticmethod
    def _key(alias: str, scope: str) -> tuple[str, str]:
        return (scope.casefold().strip(), alias.casefold().strip())

    def register(
        self,
        *,
        canonical: str,
        alias: str,
        confidence: float,
        scope: str,
        provenance: ProvenanceRef,
    ) -> None:
        bounded = min(1.0, max(0.0, float(confidence)))
        self._records[self._key(alias, scope)] = _MerchantAliasRecord(
            canonical=canonical.strip(),
            raw_alias=alias,
            confidence=bounded,
            scope=scope.strip(),
            provenance=provenance,
        )

    def reject(self, alias: str, *, scope: str) -> None:
        key = self._key(alias, scope)
        record = self._records.get(key)
        if record is None:
            return
        self._records[key] = _MerchantAliasRecord(
            canonical=record.canonical,
            raw_alias=record.raw_alias,
            confidence=record.confidence,
            scope=record.scope,
            provenance=record.provenance,
            rejected=True,
        )

    def resolve(self, raw: str, *, scope: str) -> MerchantAliasResolution:
        record = self._records.get(self._key(raw, scope))
        if record is None or record.rejected:
            return MerchantAliasResolution(raw, raw, 0.0, False, record.provenance if record else None)
        return MerchantAliasResolution(
            raw=raw,
            canonical=record.canonical,
            confidence=record.confidence,
            matched=True,
            provenance=record.provenance,
        )


@dataclass(frozen=True, slots=True)
class PersonIdentity:
    native_id: str
    display_name: str
    email: str
    marketplace_handle: str
    provenance: ProvenanceRef


@dataclass(frozen=True, slots=True)
class PersonRelationAssessment:
    confirmed: bool
    confidence: float
    reasons: tuple[str, ...]
    identities: tuple[PersonIdentity, PersonIdentity]


def assess_person_relation(left: PersonIdentity, right: PersonIdentity) -> PersonRelationAssessment:
    reasons: list[str] = []
    confidence = 0.0
    if left.email.strip() and right.email.strip() and left.email.casefold() == right.email.casefold():
        confidence = 0.95
        reasons.append("same normalized email")
    elif (
        left.marketplace_handle.strip()
        and right.marketplace_handle.strip()
        and left.marketplace_handle.casefold() == right.marketplace_handle.casefold()
    ):
        confidence = 0.90
        reasons.append("same marketplace handle")
    elif left.display_name.strip() and left.display_name.casefold() == right.display_name.casefold():
        confidence = 0.20
        reasons.append("same display name only")
    return PersonRelationAssessment(
        confirmed=confidence >= 0.80,
        confidence=confidence,
        reasons=tuple(reasons),
        identities=(left, right),
    )


@dataclass(frozen=True, slots=True)
class DocumentOccurrence:
    path: str
    content: bytes
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class LogicalDocument:
    content_hash: str
    locations: tuple[str, ...]
    metadata: dict[str, str]


def deduplicate_documents(documents: tuple[DocumentOccurrence, ...]) -> tuple[LogicalDocument, ...]:
    grouped: dict[str, list[DocumentOccurrence]] = {}
    for document in documents:
        digest = hashlib.sha256(document.content).hexdigest()
        grouped.setdefault(digest, []).append(document)

    logical: list[LogicalDocument] = []
    for digest, occurrences in grouped.items():
        logical.append(
            LogicalDocument(
                content_hash=digest,
                locations=tuple(sorted({occurrence.path for occurrence in occurrences})),
                metadata=dict(occurrences[0].metadata),
            )
        )
    logical.sort(key=lambda item: item.content_hash)
    return tuple(logical)
