from __future__ import annotations

import re
from collections.abc import Iterable

from jarvis_papa.actions import ActionCard


class SecretaryFormatter:
    """Keep every user-facing answer short, precise and immediately actionable."""

    @staticmethod
    def clean(text: str, *, max_chars: int = 520, max_sentences: int = 4) -> str:
        cleaned = re.sub(r"[*_`#>]", "", text or "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return "Je n'ai rien d'utile à ajouter pour le moment."
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+", cleaned)
            if item.strip()
        ]
        if sentences:
            cleaned = " ".join(sentences[:max_sentences])
        if len(cleaned) > max_chars:
            cleaned = cleaned[: max_chars - 3].rstrip(" ,;:-") + "..."
        return cleaned

    @classmethod
    def briefing(cls, cards: Iterable[ActionCard], newsletter_count: int = 0) -> str:
        active = list(cards)
        if not active:
            if newsletter_count:
                return cls.clean(
                    f"Rien d'important pour le moment. J'ai seulement {newsletter_count} newsletter"
                    f"{'s' if newsletter_count > 1 else ''} à ranger."
                )
            return "Rien d'important pour le moment, Robert."

        first = active[0]
        recommendation = str(first.metadata.get("recommended_action") or "").strip()
        deadline = str(first.metadata.get("deadline_text") or "").strip()
        if len(active) == 1:
            intro = "Tu as une chose importante."
        else:
            intro = f"Tu as {len(active)} choses importantes."
        details = f" Priorité : {first.source}, {first.summary}"
        if deadline:
            details += f" Échéance : {deadline}."
        if recommendation:
            details += f" Je te conseille : {recommendation}"
        elif not details.endswith("."):
            details += "."
        return cls.clean(intro + details)


secretary_formatter = SecretaryFormatter()
