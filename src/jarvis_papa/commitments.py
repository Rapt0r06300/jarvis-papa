from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Commitment:
    action: str
    deadline: str | None
    priority: str
    source_hint: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CommitmentExtractor:
    """Read-only detector for obligations in mails/documents.

    Results are suggestions. Persisting a task still goes through the normal
    authorization path, so external text can never create a durable commitment by itself.
    """

    _action_patterns = (
        r"(?:merci de|veuillez|il faut|vous devez|nous vous demandons de)\s+([^.!?]{4,220})",
        r"(?:à|a)\s+(?:envoyer|transmettre|retourner|fournir|compléter|completer)\s+([^.!?]{3,180})",
    )
    _deadlines = (
        r"(?:avant|au plus tard|d'ici|pour)\s+(?:le\s+)?([0-3]?\d[/-][01]?\d(?:[/-]\d{2,4})?)",
        r"(?:avant|au plus tard|d'ici|pour)\s+(?:le\s+)?([0-3]?\d\s+(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)(?:\s+\d{4})?)",
        r"(?:avant|au plus tard|d'ici|pour)\s+(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
    )
    _urgent = ("urgent", "mise en demeure", "dernier rappel", "sous 24", "sous 48")

    def detect(self, text: str, *, source_hint: str = "document") -> list[Commitment]:
        clean = re.sub(r"\s+", " ", str(text)).strip()
        if not clean:
            return []
        deadline = self._deadline(clean)
        priority = "urgent" if any(term in clean.casefold() for term in self._urgent) else (
            "important" if deadline else "normal"
        )
        commitments: list[Commitment] = []
        seen: set[str] = set()
        for pattern in self._action_patterns:
            for match in re.finditer(pattern, clean, flags=re.IGNORECASE):
                action = self._sanitize(match.group(1))
                if not action or action.casefold() in seen:
                    continue
                seen.add(action.casefold())
                confidence = 0.9 if deadline else 0.78
                commitments.append(
                    Commitment(
                        action=action,
                        deadline=deadline,
                        priority=priority,
                        source_hint=source_hint[:160],
                        confidence=confidence,
                    )
                )
                if len(commitments) >= 5:
                    return commitments
        return commitments

    def _deadline(self, text: str) -> str | None:
        for pattern in self._deadlines:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return self._sanitize(match.group(1))[:100]
        return None

    @staticmethod
    def _sanitize(text: str) -> str:
        value = " ".join(text.split()).strip(" ,;:-")
        dangerous = (
            "ignore les instructions",
            "ignore previous instructions",
            "system prompt",
            "execute powershell",
            "exécute powershell",
        )
        if any(marker in value.casefold() for marker in dangerous):
            return ""
        return value[:240]


commitment_extractor = CommitmentExtractor()
