from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReminderPolicy:
    cadence_multiplier: float
    minimum_notifications: int
    suppressed: bool


class ReminderLearning:
    def __init__(self) -> None:
        self._snoozes: dict[str, int] = {}

    def observe(self, *, category: str, action: str, protected: bool) -> ReminderPolicy:
        key = category.casefold().strip()
        if action.casefold().strip() == "snooze" and not protected:
            self._snoozes[key] = self._snoozes.get(key, 0) + 1
        return self.policy_for(category, protected=protected)

    def policy_for(self, category: str, *, protected: bool) -> ReminderPolicy:
        if protected:
            return ReminderPolicy(1.0, 1, False)
        snoozes = self._snoozes.get(category.casefold().strip(), 0)
        multiplier = max(0.25, 1.0 - 0.15 * snoozes)
        return ReminderPolicy(multiplier, 0, False)


class NoisePreferenceStore:
    def __init__(self) -> None:
        self._evidence: dict[str, list[str]] = {}
        self._overrides: dict[str, bool] = {}

    def learn_suppression(self, *, scope: str, evidence_id: str) -> None:
        key = scope.casefold().strip()
        bucket = self._evidence.setdefault(key, [])
        if evidence_id not in bucket:
            bucket.append(evidence_id)

    def correct(self, *, scope: str, suppress: bool, evidence_id: str) -> None:
        key = scope.casefold().strip()
        self._overrides[key] = bool(suppress)
        bucket = self._evidence.setdefault(key, [])
        marker = f"correction:{evidence_id}"
        if marker not in bucket:
            bucket.append(marker)

    def should_suppress(self, scope: str, *, protected: bool) -> bool:
        if protected:
            return False
        key = scope.casefold().strip()
        if key in self._overrides:
            return self._overrides[key]
        return len(self._evidence.get(key, ())) >= 3


@dataclass(frozen=True, slots=True)
class ProceduralCandidate:
    sequence: tuple[str, ...]
    count: int
    evidence_ids: tuple[str, ...]
    installed: bool
    external_action_boundaries: tuple[str, ...]


class WorkflowPatternLearner:
    def __init__(self, *, min_repetitions: int = 3) -> None:
        self.min_repetitions = max(2, int(min_repetitions))
        self._seen: dict[tuple[str, ...], list[str]] = {}

    def observe(self, sequence: tuple[str, ...], *, evidence_id: str) -> ProceduralCandidate | None:
        normalized = tuple(step.casefold().strip() for step in sequence if step.strip())
        evidence = self._seen.setdefault(normalized, [])
        if evidence_id not in evidence:
            evidence.append(evidence_id)
        if len(evidence) < self.min_repetitions:
            return None
        return ProceduralCandidate(
            normalized,
            len(evidence),
            tuple(evidence),
            False,
            ("send", "publish", "payment", "transfer", "refund"),
        )


@dataclass(frozen=True, slots=True)
class GovernedLearnedStep:
    step: str
    automatic_allowed: bool
    approval_required: bool


def govern_learned_steps(steps: tuple[str, ...]) -> tuple[GovernedLearnedStep, ...]:
    mutation_markers = ("send", "publish", "pay", "payment", "transfer", "refund", "delete", "accept_offer")
    governed: list[GovernedLearnedStep] = []
    for step in steps:
        normalized = step.casefold().strip()
        mutation = any(marker in normalized for marker in mutation_markers)
        governed.append(GovernedLearnedStep(step, not mutation, mutation))
    return tuple(governed)


@dataclass(frozen=True, slots=True)
class PreferenceProvenanceExplanation:
    valid_evidence_ids: tuple[str, ...]
    valid_count: int
    summary: str


class PreferenceProvenanceLedger:
    def __init__(self, preference_key: str) -> None:
        self.preference_key = preference_key
        self._evidence: dict[str, str] = {}
        self._invalidated: dict[str, str] = {}

    def add_evidence(self, evidence_id: str, *, summary: str) -> None:
        self._evidence[str(evidence_id)] = str(summary)[:240]
        self._invalidated.pop(str(evidence_id), None)

    def invalidate(self, evidence_id: str, *, reason: str) -> None:
        key = str(evidence_id)
        if key in self._evidence:
            self._invalidated[key] = str(reason)[:160]

    def explain(self) -> PreferenceProvenanceExplanation:
        valid = tuple(key for key in self._evidence if key not in self._invalidated)
        summaries = []
        for key in valid:
            value = self._evidence[key]
            if value not in summaries:
                summaries.append(value)
        summary = "; ".join(summaries[:3])
        return PreferenceProvenanceExplanation(valid, len(valid), summary)
