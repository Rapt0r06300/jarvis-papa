from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class ReferentResolution:
    entity_id: str
    confident: bool
    source: str
    message: str


@dataclass(frozen=True, slots=True)
class ReferentContext:
    visible_entity_ids: tuple[str, ...]

    def resolve(self, phrase: str) -> ReferentResolution:
        normalized = " ".join(phrase.casefold().strip().split())
        ordinal_map = {
            "le premier": 0,
            "la première": 0,
            "le deuxième": 1,
            "la deuxième": 1,
            "le second": 1,
            "la seconde": 1,
            "le troisième": 2,
            "la troisième": 2,
        }
        if normalized in ordinal_map:
            index = ordinal_map[normalized]
            if index < len(self.visible_entity_ids):
                return ReferentResolution(
                    self.visible_entity_ids[index],
                    True,
                    "visible_context",
                    "Référence comprise depuis les éléments affichés.",
                )
        if (
            normalized in {"celui-là", "celui la", "celle-là", "celle la"}
            and len(self.visible_entity_ids) == 1
        ):
            return ReferentResolution(
                self.visible_entity_ids[0],
                True,
                "visible_context",
                "Référence comprise depuis l’élément affiché.",
            )
        return ReferentResolution(
            "",
            False,
            "visible_context",
            "Référence ambiguë : indique un élément plus précis.",
        )


@dataclass(frozen=True, slots=True)
class SituationContextItem:
    situation_id: str
    domain: str
    structured_summary: dict[str, str]
    latest_messages: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SituationLLMContext:
    situation_id: str
    domain: str
    structured_summary: dict[str, str]
    latest_messages: tuple[str, ...]
    evidence_refs: tuple[str, ...]


def _safe_summary(summary: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in summary.items()
        if key.casefold().strip() not in _SECRET_KEYS
    }


def build_situation_context(
    situation_id: str,
    items: tuple[SituationContextItem, ...],
) -> SituationLLMContext:
    selected = next((item for item in items if item.situation_id == situation_id), None)
    if selected is None:
        return SituationLLMContext(situation_id, "", {}, (), ())
    return SituationLLMContext(
        selected.situation_id,
        selected.domain,
        _safe_summary(selected.structured_summary),
        tuple(message[:1000] for message in selected.latest_messages[-3:]),
        selected.evidence_refs[:12],
    )


@dataclass(frozen=True, slots=True)
class FactFreshness:
    oldest_age_seconds: float
    newest_age_seconds: float
    current: bool
    label: str


def assess_fact_freshness(
    provenance: tuple[ProvenanceRef, ...],
    *,
    now: float,
    max_age_seconds: float,
) -> FactFreshness:
    if not provenance:
        return FactFreshness(float("inf"), float("inf"), False, "source à vérifier")
    ages = tuple(max(0.0, now - ref.observed_at) for ref in provenance)
    oldest = max(ages)
    newest = min(ages)
    current = oldest <= max_age_seconds
    return FactFreshness(
        oldest,
        newest,
        current,
        "information actuelle" if current else "dernière information connue",
    )


@dataclass(frozen=True, slots=True)
class SourceAction:
    enabled: bool
    label: str
    source: str
    source_id: str
    observed_at: float | None


def build_source_action(provenance: ProvenanceRef | None) -> SourceAction:
    if provenance is None or not provenance.source_id:
        return SourceAction(False, "Source indisponible", "", "", None)
    return SourceAction(
        True,
        "Ouvrir la source",
        provenance.source,
        provenance.source_id,
        provenance.observed_at,
    )


@dataclass(frozen=True, slots=True)
class FusionCase:
    case_id: str
    should_merge: bool
    predicted_merge: bool
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class FusionMetrics:
    correct_merges: int
    missed_merges: int
    false_merges: int
    correct_non_merges: int
    total: int
    mean_calibration_error: float


def evaluate_fusion_cases(cases: tuple[FusionCase, ...]) -> FusionMetrics:
    correct_merges = sum(case.should_merge and case.predicted_merge for case in cases)
    missed_merges = sum(case.should_merge and not case.predicted_merge for case in cases)
    false_merges = sum(not case.should_merge and case.predicted_merge for case in cases)
    correct_non_merges = sum(not case.should_merge and not case.predicted_merge for case in cases)
    errors = [abs(case.confidence - (1.0 if case.should_merge else 0.0)) for case in cases]
    calibration = sum(errors) / len(errors) if errors else 0.0
    return FusionMetrics(
        int(correct_merges),
        int(missed_merges),
        int(false_merges),
        int(correct_non_merges),
        len(cases),
        calibration,
    )
