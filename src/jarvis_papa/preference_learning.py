from __future__ import annotations

from dataclasses import dataclass

from .memory import MemoryItem, MemoryStore


@dataclass(frozen=True, slots=True)
class PreferenceEvidence:
    key: str
    value: str
    scope: str
    count: int
    confidence: float
    evidence_ids: tuple[str, ...]
    expires_at: float | None = None


class PreferenceAccumulator:
    def __init__(self, key: str, value: str, *, scope: str, expires_at: float | None = None) -> None:
        self.key = key
        self.value = value
        self.scope = scope
        self.expires_at = expires_at
        self._evidence_ids: list[str] = []

    def observe(self, evidence_id: str) -> PreferenceEvidence:
        cleaned = " ".join(str(evidence_id).split()).strip()[:160]
        if cleaned and cleaned not in self._evidence_ids:
            self._evidence_ids.append(cleaned)
        count = len(self._evidence_ids)
        confidence = min(0.95, 0.35 + max(0, count - 1) * 0.20)
        return PreferenceEvidence(
            self.key,
            self.value,
            self.scope,
            count,
            confidence,
            tuple(self._evidence_ids),
            self.expires_at,
        )


def project_preference_to_memory(store: MemoryStore, evidence: PreferenceEvidence) -> MemoryItem:
    key = f"{evidence.scope}:{evidence.key}"
    return store.remember(
        "preference",
        key,
        evidence.value,
        provenance=f"learned:{evidence.scope}",
        confidence=evidence.confidence,
        expires_at=evidence.expires_at,
    )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    promoted: bool
    evidence_count: int
    scope: str
    audit_summary: str


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    min_count: int = 3
    min_confidence: float = 0.60

    def evaluate(self, evidence: PreferenceEvidence) -> PromotionDecision:
        promoted = evidence.count >= self.min_count and evidence.confidence >= self.min_confidence
        summary = (
            f"scope={evidence.scope}; evidence_count={evidence.count}; "
            f"confidence={evidence.confidence:.2f}; promoted={str(promoted).lower()}"
        )
        return PromotionDecision(promoted, evidence.count, evidence.scope, summary)


@dataclass(frozen=True, slots=True)
class ReplyStylePreference:
    preference: str
    scope: str
    count: int
    confidence: float
    evidence_ids: tuple[str, ...]


class ReplyStyleLearner:
    def __init__(self, *, scope: str) -> None:
        self.scope = scope
        self._concise = PreferenceAccumulator("reply_style", "concis", scope=scope)
        self._neutral = PreferenceAccumulator("reply_style", "équilibré", scope=scope)

    def observe_edit(
        self,
        *,
        original_length: int,
        final_length: int,
        approved: bool,
        evidence_id: str,
    ) -> ReplyStylePreference:
        is_concise = approved and original_length > 0 and final_length <= original_length * 0.75
        snapshot = (self._concise if is_concise else self._neutral).observe(evidence_id)
        return ReplyStylePreference(
            snapshot.value,
            snapshot.scope,
            snapshot.count,
            snapshot.confidence,
            snapshot.evidence_ids,
        )


@dataclass(frozen=True, slots=True)
class NegotiationRecommendation:
    suggested_decision: str
    preference_scope: str
    confidence: float
    autonomous_action_allowed: bool = False
    can_accept_offer: bool = False
    can_refuse_offer: bool = False


class NegotiationPreferenceLearner:
    def __init__(self, *, scope: str) -> None:
        self.scope = scope
        self._rejections: list[tuple[float, str]] = []
        self._acceptances: list[tuple[float, str]] = []

    def observe_decision(self, *, discount_percent: float, decision: str, evidence_id: str) -> None:
        normalized = decision.casefold().strip()
        record = (max(0.0, float(discount_percent)), str(evidence_id)[:160])
        if normalized == "reject":
            self._rejections.append(record)
        elif normalized == "accept":
            self._acceptances.append(record)

    def recommend(self, *, discount_percent: float) -> NegotiationRecommendation:
        discount = max(0.0, float(discount_percent))
        if len(self._rejections) >= 3:
            reject_floor = min(value for value, _ in self._rejections)
            if discount >= reject_floor:
                confidence = min(0.95, 0.55 + 0.10 * len(self._rejections))
                return NegotiationRecommendation("reject", self.scope, confidence)
        if len(self._acceptances) >= 3:
            accept_ceiling = max(value for value, _ in self._acceptances)
            if discount <= accept_ceiling:
                confidence = min(0.95, 0.55 + 0.10 * len(self._acceptances))
                return NegotiationRecommendation("accept", self.scope, confidence)
        return NegotiationRecommendation("verify", self.scope, 0.35)
