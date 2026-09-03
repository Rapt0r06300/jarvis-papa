from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RetentionMode(StrEnum):
    DURABLE = "durable"
    BOUNDED = "bounded"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    mode: RetentionMode
    max_age_seconds: int | None
    may_promote: bool


_RETENTION_POLICIES = {
    "public": RetentionPolicy(RetentionMode.DURABLE, None, True),
    "personal": RetentionPolicy(RetentionMode.DURABLE, None, True),
    "sensitive": RetentionPolicy(RetentionMode.BOUNDED, 7 * 24 * 3600, False),
    "highly_sensitive": RetentionPolicy(RetentionMode.FORBIDDEN, 0, False),
}


def retention_policy(sensitivity: str) -> RetentionPolicy:
    key = str(sensitivity).casefold().strip().replace("-", "_").replace(" ", "_")
    return _RETENTION_POLICIES.get(
        key,
        RetentionPolicy(RetentionMode.BOUNDED, 24 * 3600, False),
    )


class PickupCodeRetention:
    """Ephemeral parcel-code storage that is deliberately outside durable memory."""

    def __init__(self, *, default_ttl_seconds: int = 24 * 3600) -> None:
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))
        self._codes: dict[str, tuple[str, float]] = {}

    def retain(
        self,
        situation_id: str,
        code: str,
        *,
        now: float,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else max(1, int(ttl_seconds))
        key = str(situation_id).strip()
        self._codes[key] = (str(code).strip()[:128], float(now) + ttl)

    def get(self, situation_id: str, *, now: float) -> str | None:
        key = str(situation_id).strip()
        item = self._codes.get(key)
        if item is None:
            return None
        code, expires_at = item
        if float(now) >= expires_at:
            self._codes.pop(key, None)
            return None
        return code

    def complete(self, situation_id: str) -> None:
        self._codes.pop(str(situation_id).strip(), None)

    @staticmethod
    def durable_memory_payload() -> tuple[()]:
        return ()


@dataclass(frozen=True, slots=True)
class PreferenceCard:
    title: str
    detail: str
    confidence: float
    source_count: int


def render_preference_card(
    *,
    label: str,
    confidence: float,
    source_count: int,
) -> PreferenceCard:
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    count = max(0, int(source_count))
    tentative = bounded_confidence < 0.75 or count < 3
    suffix = " · à confirmer" if tentative else ""
    return PreferenceCard(
        title=f"Tu préfères {str(label).strip()}",
        detail=f"Basé sur {count} observation(s){suffix}",
        confidence=bounded_confidence,
        source_count=count,
    )


@dataclass(frozen=True, slots=True)
class ControlledPreference:
    key: str
    value: str
    provenance: str
    confidence: float
    evidence_ids: tuple[str, ...]


class PreferenceControls:
    def __init__(self) -> None:
        self._preferences: dict[str, ControlledPreference] = {}

    def correct(self, key: str, value: str, *, evidence_id: str) -> ControlledPreference:
        normalized = str(key).casefold().strip()
        record = ControlledPreference(
            key=normalized,
            value=str(value).strip()[:500],
            provenance="explicit_user_correction",
            confidence=1.0,
            evidence_ids=(str(evidence_id),),
        )
        self._preferences[normalized] = record
        return record

    def forget(self, key: str) -> bool:
        return self._preferences.pop(str(key).casefold().strip(), None) is not None

    def get(self, key: str) -> ControlledPreference | None:
        return self._preferences.get(str(key).casefold().strip())

    def context_for(self, scope: str) -> str:
        key = str(scope).casefold().strip()
        record = self._preferences.get(key)
        if record is None:
            return ""
        return f"{record.key}: {record.value} (source: correction explicite)"
