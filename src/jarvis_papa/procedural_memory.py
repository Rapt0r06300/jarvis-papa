from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class ProcedureCandidate:
    candidate_id: str
    key: str
    summary: str
    steps: tuple[str, ...]
    evidence_count: int
    success_rate: float
    created_at: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["steps"] = list(self.steps)
        return payload


@dataclass(frozen=True, slots=True)
class Procedure:
    procedure_id: str
    key: str
    summary: str
    steps: tuple[str, ...]
    success_count: int
    failure_count: int
    confidence: float
    provenance: str
    enabled: bool
    updated_at: float

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total else 0.0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["steps"] = list(self.steps)
        payload["success_rate"] = round(self.success_rate, 4)
        return payload


class ProceduralMemoryStore:
    """Stores only explicitly promoted reusable procedures.

    Candidate generation is read-only. Promotion is intentionally a separate
    method so API routes can require two exact authorizations before persistence.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "procedural-memory.sqlite3")
        self._init_db()

    def candidate_from_trace(
        self,
        *,
        key: str,
        summary: str,
        steps: list[str] | tuple[str, ...],
        evidence_count: int,
        success_rate: float,
    ) -> ProcedureCandidate | None:
        clean_steps = tuple(self._clean_step(step) for step in steps if self._clean_step(step))[:20]
        if len(clean_steps) < 2 or evidence_count < 2 or success_rate < 0.75:
            return None
        return ProcedureCandidate(
            candidate_id=uuid4().hex,
            key=self._clean_key(key),
            summary=" ".join(summary.split()).strip()[:600],
            steps=clean_steps,
            evidence_count=max(0, int(evidence_count)),
            success_rate=max(0.0, min(float(success_rate), 1.0)),
            created_at=time.time(),
        )

    def promote(self, candidate: ProcedureCandidate, *, provenance: str = "user_approved") -> Procedure:
        now = time.time()
        confidence = min(1.0, 0.55 + candidate.success_rate * 0.35 + min(candidate.evidence_count, 10) * 0.01)
        existing = self.get_by_key(candidate.key)
        procedure_id = existing.procedure_id if existing else uuid4().hex
        success_count = max(existing.success_count if existing else 0, candidate.evidence_count)
        failure_count = existing.failure_count if existing else 0
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                """
                INSERT INTO procedures(
                    procedure_id, key, summary, steps_json, success_count, failure_count,
                    confidence, provenance, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(key) DO UPDATE SET
                    summary=excluded.summary,
                    steps_json=excluded.steps_json,
                    success_count=MAX(procedures.success_count, excluded.success_count),
                    confidence=MAX(procedures.confidence, excluded.confidence),
                    provenance=excluded.provenance,
                    enabled=1,
                    updated_at=excluded.updated_at
                """,
                (
                    procedure_id,
                    candidate.key,
                    candidate.summary,
                    json.dumps(candidate.steps, ensure_ascii=False),
                    success_count,
                    failure_count,
                    confidence,
                    provenance[:120],
                    now,
                ),
            )
        return self.get_by_key(candidate.key) or Procedure(
            procedure_id,
            candidate.key,
            candidate.summary,
            candidate.steps,
            success_count,
            failure_count,
            confidence,
            provenance,
            True,
            now,
        )

    def record_outcome(self, procedure_id: str, *, ok: bool) -> None:
        field = "success_count" if ok else "failure_count"
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                f"UPDATE procedures SET {field}={field}+1, updated_at=? WHERE procedure_id=?",  # noqa: S608
                (time.time(), procedure_id),
            )

    def search(self, query: str, limit: int = 5) -> list[Procedure]:
        tokens = [token.casefold() for token in query.split() if len(token) >= 2]
        rows = self._all_enabled()
        scored: list[tuple[float, Procedure]] = []
        for item in rows:
            haystack = f"{item.key} {item.summary} {' '.join(item.steps)}".casefold()
            matches = sum(token in haystack for token in tokens)
            if not matches:
                continue
            score = matches + item.confidence + item.success_rate
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[: max(1, min(int(limit), 10))]]

    def get_by_key(self, key: str) -> Procedure | None:
        clean = self._clean_key(key)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM procedures WHERE key=? LIMIT 1", (clean,)).fetchone()
        return self._from_row(row) if row is not None else None

    def list(self, limit: int = 50) -> list[Procedure]:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM procedures ORDER BY enabled DESC, confidence DESC, updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def disable(self, procedure_id: str) -> bool:
        with sqlite3.connect(self.path, timeout=5) as connection:
            result = connection.execute(
                "UPDATE procedures SET enabled=0, updated_at=? WHERE procedure_id=?",
                (time.time(), procedure_id),
            )
        return bool(result.rowcount)

    def status(self) -> dict[str, object]:
        rows = self.list(limit=100)
        return {
            "enabled": sum(item.enabled for item in rows),
            "stored": len(rows),
            "policy": "candidate_requires_evidence_and_explicit_promotion",
        }

    def _all_enabled(self) -> list[Procedure]:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM procedures WHERE enabled=1 ORDER BY confidence DESC LIMIT 100"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS procedures(
                    procedure_id TEXT PRIMARY KEY,
                    key TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0,
                    provenance TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Procedure:
        try:
            steps_raw = json.loads(str(row["steps_json"]))
        except json.JSONDecodeError:
            steps_raw = []
        steps = tuple(str(item)[:500] for item in steps_raw if isinstance(item, str))[:20]
        return Procedure(
            procedure_id=str(row["procedure_id"]),
            key=str(row["key"]),
            summary=str(row["summary"]),
            steps=steps,
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            confidence=float(row["confidence"]),
            provenance=str(row["provenance"]),
            enabled=bool(row["enabled"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _clean_key(value: str) -> str:
        clean = " ".join(value.casefold().split()).strip()
        return clean[:180] or "procedure"

    @staticmethod
    def _clean_step(value: str) -> str:
        return " ".join(str(value).split()).strip()[:500]


procedural_memory = ProceduralMemoryStore()
