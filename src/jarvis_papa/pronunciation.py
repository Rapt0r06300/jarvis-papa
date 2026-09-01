from __future__ import annotations

import json
from pathlib import Path

from jarvis_papa.config import settings


_DEFAULTS = {
    "Thunderbird": "Thunderbird",
    "Numericable": "Numéricable",
    "Qwen": "Kwen",
    "Ollama": "Olama",
    "PDF": "P D F",
    "EDF": "E D F",
    "IBAN": "i-ban",
}


class PronunciationLexicon:
    """User-owned pronunciation overrides; never auto-writes learned entries."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "pronunciation.json")

    def apply(self, text: str) -> str:
        output = str(text)
        mapping = dict(_DEFAULTS)
        mapping.update(self._load())
        for source, replacement in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            if source:
                output = output.replace(source, replacement)
        return output

    def preview_update(self, source: str, pronunciation: str) -> dict[str, object]:
        return {
            "action_key": "voice.pronunciation.update",
            "description": f"Enregistrer la prononciation personnalisée de « {source[:80]} ».",
            "binding": {
                "source": source.strip()[:120],
                "pronunciation": pronunciation.strip()[:160],
            },
        }

    def update(self, source: str, pronunciation: str) -> bool:
        key = " ".join(source.split()).strip()[:120]
        value = " ".join(pronunciation.split()).strip()[:160]
        if not key or not value:
            return False
        mapping = self._load()
        mapping[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
        except OSError:
            temp.unlink(missing_ok=True)
            return False
        return True

    def _load(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key)[:120]: str(value)[:160]
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str)
        }


pronunciation_lexicon = PronunciationLexicon()
