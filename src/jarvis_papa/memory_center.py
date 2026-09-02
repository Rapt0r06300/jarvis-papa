from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass

from jarvis_papa.memory import MemoryItem
from jarvis_papa.memory_semantic import semantic_memory_store
from jarvis_papa.procedural_memory import procedural_memory


@dataclass(frozen=True, slots=True)
class MemoryView:
    category: str
    key: str
    value: str
    provenance: str
    confidence: float
    updated_at: float
    expires_at: float | None
    sanitized: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MemoryCenter:
    """Human-readable view over protected durable and procedural memory."""

    def list(self, *, limit: int = 100) -> dict[str, object]:
        items = self._active(max(1, min(int(limit), 200)))
        procedures = procedural_memory.list(limit=30)
        return {
            "ok": True,
            "state": "success",
            "memories": [self._view(item).to_dict() for item in items],
            "procedures": [item.to_dict() for item in procedures],
            "detail": f"Jarvis conserve {len(items)} souvenir(s) durable(s) visible(s).",
        }

    @staticmethod
    def update_plan(category: str, key: str, value: str) -> dict[str, object]:
        binding = {
            "category": MemoryCenter._clean(category, 80),
            "key": MemoryCenter._clean(key, 160),
            "value": " ".join(str(value).split()).strip()[:6000],
        }
        return {
            "ok": bool(binding["category"] and binding["key"] and binding["value"]),
            "action_key": "memory.update",
            "binding": binding,
            "description": (
                f"Jarvis va corriger le souvenir « {binding['key']} » dans la catégorie "
                f"« {binding['category']} »."
            ),
        }

    @staticmethod
    def update(category: str, key: str, value: str) -> dict[str, object]:
        item = semantic_memory_store.remember(
            category,
            key,
            value,
            provenance="user_approved",
            confidence=1.0,
        )
        if item.sanitized:
            return {
                "ok": False,
                "state": "failed",
                "detail": "Ce contenu ressemble à un secret ou à une instruction non fiable ; Jarvis refuse de le mémoriser.",
                "reason": item.reason,
            }
        return {
            "ok": True,
            "state": "success",
            "memory": item.to_dict(),
            "detail": "Le souvenir a été corrigé.",
        }

    @staticmethod
    def forget_plan(category: str, key: str) -> dict[str, object]:
        binding = {
            "category": MemoryCenter._clean(category, 80),
            "key": MemoryCenter._clean(key, 160),
        }
        return {
            "ok": bool(binding["category"] and binding["key"]),
            "action_key": "memory.forget",
            "binding": binding,
            "description": f"Jarvis va oublier le souvenir « {binding['key']} ».",
        }

    def forget(self, category: str, key: str) -> dict[str, object]:
        category = self._clean(category, 80)
        key = self._clean(key, 160)
        try:
            with sqlite3.connect(semantic_memory_store.path, timeout=5) as connection:
                cursor = connection.execute(
                    "DELETE FROM memories WHERE category=? AND key=?",
                    (category, key),
                )
                deleted = max(0, int(cursor.rowcount or 0))
        except sqlite3.Error as exc:
            return {
                "ok": False,
                "state": "failed",
                "detail": f"Le souvenir n'a pas pu être supprimé ({type(exc).__name__}).",
            }
        return {
            "ok": bool(deleted),
            "state": "success" if deleted else "failed",
            "detail": "Le souvenir a été oublié." if deleted else "Ce souvenir n'existe plus.",
        }

    @staticmethod
    def procedure_disable_plan(procedure_id: str, summary: str = "") -> dict[str, object]:
        binding = {"procedure_id": MemoryCenter._clean(procedure_id, 100)}
        label = " ".join(str(summary).split()).strip()[:160] or "cette habitude"
        return {
            "ok": bool(binding["procedure_id"]),
            "action_key": "memory.procedure.disable",
            "binding": binding,
            "description": f"Jarvis va désactiver la procédure mémorisée « {label} ».",
        }

    @staticmethod
    def procedure_disable(procedure_id: str) -> dict[str, object]:
        disabled = procedural_memory.disable(MemoryCenter._clean(procedure_id, 100))
        return {
            "ok": disabled,
            "state": "success" if disabled else "failed",
            "detail": "La procédure a été désactivée." if disabled else "La procédure n'a pas été trouvée.",
        }

    def _active(self, limit: int) -> list[MemoryItem]:
        try:
            with sqlite3.connect(semantic_memory_store.path, timeout=5) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT category, key, value, updated_at, provenance, confidence,
                           expires_at, created_at, sanitized, reason
                    FROM memories
                    WHERE expires_at IS NULL OR expires_at > ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (time.time(), limit),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [semantic_memory_store._from_row(row) for row in rows]

    @staticmethod
    def _view(item: MemoryItem) -> MemoryView:
        return MemoryView(
            item.category,
            item.key,
            item.value,
            item.provenance,
            item.confidence,
            item.updated_at,
            item.expires_at,
            item.sanitized,
        )

    @staticmethod
    def _clean(value: str, limit: int) -> str:
        return " ".join(str(value).split()).strip()[:limit]


memory_center = MemoryCenter()
