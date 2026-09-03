from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jarvis_papa.config import settings

_SCHEMA_VERSION = 2
_RECALL_TOKEN = re.compile(r"[\wÀ-ÿ-]{3,}", re.UNICODE)
_SECRET_WORDS = (
    "mot de passe",
    "password",
    "api key",
    "api_key",
    "clé api",
    "cle api",
    "access token",
    "refresh token",
    "bearer token",
    "auth token",
    "session token",
    "cookie",
    "session cookie",
    "sessionid",
    "private key",
    "clé privée",
    "cle privee",
    "seed phrase",
    "phrase de récupération",
    "phrase de recuperation",
    "cvv",
    "cryptogramme",
    "code pin",
    "otp",
    "otp code",
    "code otp",
    "2fa",
    "code 2fa",
    "code sms",
    "sms code",
    "code de confirmation",
    "code de validation",
    "one-time password",
    "one time password",
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.IGNORECASE),
    re.compile(r"\b(?:bearer\s+)[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore les instructions précédentes",
    "ignore les instructions precedentes",
    "oublie tes instructions",
    "system message:",
    "system prompt",
    "execute powershell",
    "exécute powershell",
    "execute cmd",
    "supprime tous les fichiers",
    "delete all files",
    "reveal your prompt",
    "révèle ton prompt",
    "revele ton prompt",
    "jailbreak",
)
_SENSITIVE_METADATA_KEYS = {
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
class MemoryItem:
    category: str
    key: str
    value: str
    updated_at: float
    provenance: str = "legacy"
    confidence: float = 1.0
    expires_at: float | None = None
    created_at: float = 0.0
    sanitized: bool = False
    reason: str = ""

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"expired": self.expired}


@dataclass(frozen=True, slots=True)
class Habit:
    action: str
    target: str
    count: int
    last_seen: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MemoryStore:
    """Local, bounded and provenance-aware durable memory.

    Conversation/session state lives elsewhere. Durable memory stores only small,
    explicit facts/preferences and never keeps plaintext secrets or prompt-like
    instructions. Existing v1 databases are upgraded in place.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    provenance TEXT NOT NULL DEFAULT 'legacy',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    expires_at REAL,
                    created_at REAL NOT NULL DEFAULT 0,
                    sanitized INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(category, key)
                );
                CREATE TABLE IF NOT EXISTS action_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_action_events_action_target
                ON action_events(action, target);
                CREATE INDEX IF NOT EXISTS idx_memories_updated
                ON memories(updated_at DESC);
                """
            )
            self._migrate_schema(connection)

    @staticmethod
    def _migrate_schema(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(memories)").fetchall()
        }
        migrations = {
            "provenance": "ALTER TABLE memories ADD COLUMN provenance TEXT NOT NULL DEFAULT 'legacy'",
            "confidence": "ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0",
            "expires_at": "ALTER TABLE memories ADD COLUMN expires_at REAL",
            "created_at": "ALTER TABLE memories ADD COLUMN created_at REAL NOT NULL DEFAULT 0",
            "sanitized": "ALTER TABLE memories ADD COLUMN sanitized INTEGER NOT NULL DEFAULT 0",
            "reason": "ALTER TABLE memories ADD COLUMN reason TEXT NOT NULL DEFAULT ''",
        }
        for name, statement in migrations.items():
            if name not in columns:
                connection.execute(statement)
        connection.execute(
            "UPDATE memories SET created_at = updated_at WHERE created_at IS NULL OR created_at <= 0"
        )

    def remember(
        self,
        category: str,
        key: str,
        value: str,
        *,
        provenance: str = "user_approved",
        confidence: float = 1.0,
        expires_at: float | None = None,
    ) -> MemoryItem:
        category = self._clean_identifier(category, 80)
        key = self._clean_identifier(key, 160)
        provenance = self._clean_identifier(provenance or "user_approved", 80)
        confidence = max(0.0, min(1.0, float(confidence)))
        sanitized_value, sanitized, reason = self._sanitize_memory_value(
            category=category,
            key=key,
            value=value,
        )
        now = time.time()
        expiry = float(expires_at) if expires_at is not None else None
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM memories WHERE category = ? AND key = ?",
                (category, key),
            ).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            if created_at <= 0:
                created_at = now
            connection.execute(
                """
                INSERT INTO memories(
                    category, key, value, updated_at, provenance, confidence,
                    expires_at, created_at, sanitized, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, key)
                DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at,
                    provenance=excluded.provenance,
                    confidence=excluded.confidence,
                    expires_at=excluded.expires_at,
                    sanitized=excluded.sanitized,
                    reason=excluded.reason
                """,
                (
                    category,
                    key,
                    sanitized_value,
                    now,
                    provenance,
                    confidence,
                    expiry,
                    created_at,
                    int(sanitized),
                    reason,
                ),
            )
        return MemoryItem(
            category=category,
            key=key,
            value=sanitized_value,
            updated_at=now,
            provenance=provenance,
            confidence=confidence,
            expires_at=expiry,
            created_at=created_at,
            sanitized=sanitized,
            reason=reason,
        )

    def recall(self, query: str, limit: int = 8) -> list[MemoryItem]:
        tokens = [token.casefold() for token in _RECALL_TOKEN.findall(query)][:8]
        if not tokens:
            return []
        clauses: list[str] = []
        params: list[object] = []
        for token in tokens:
            clauses.append("(lower(key) LIKE ? OR lower(value) LIKE ? OR lower(category) LIKE ?)")
            pattern = f"%{token}%"
            params.extend((pattern, pattern, pattern))
        params.extend((time.time(), max(1, min(int(limit), 20))))
        sql = (
            "SELECT category, key, value, updated_at, provenance, confidence, "
            "expires_at, created_at, sanitized, reason FROM memories WHERE ("
            + " OR ".join(clauses)
            + ") AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def record_action(
        self,
        action: str,
        target: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        clean_action = self._clean_identifier(action, 120)
        clean_target, _, _ = self._sanitize_memory_value(
            category="action_history",
            key=clean_action,
            value=target[:1000],
        )
        clean_metadata = self._redact_structure(metadata or {})
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO action_events(action, target, metadata, created_at) VALUES (?, ?, ?, ?)",
                (
                    clean_action,
                    clean_target,
                    json.dumps(clean_metadata, ensure_ascii=False, default=str)[:12000],
                    time.time(),
                ),
            )

    def habits(self, *, min_count: int = 3, limit: int = 12) -> list[Habit]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT action, target, COUNT(*) AS count, MAX(created_at) AS last_seen
                FROM action_events
                GROUP BY action, target
                HAVING COUNT(*) >= ?
                ORDER BY count DESC, last_seen DESC
                LIMIT ?
                """,
                (max(2, int(min_count)), max(1, min(int(limit), 30))),
            ).fetchall()
        return [Habit(row["action"], row["target"], row["count"], row["last_seen"]) for row in rows]

    def context_for(self, query: str, limit: int = 6) -> str:
        items = self.recall(query, limit=limit)
        if not items:
            return ""
        lines: list[str] = []
        for item in items:
            confidence = f"{item.confidence:.2f}"
            lines.append(
                f"- [{item.category}/{item.key}] {item.value} "
                f"(provenance={item.provenance}; confiance={confidence})"
            )
        return "\n".join(lines)

    def purge_expired(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (time.time(),),
            )
            return max(0, int(cursor.rowcount or 0))

    def status(self) -> dict[str, object]:
        with self._connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            active = int(
                connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE expires_at IS NULL OR expires_at > ?",
                    (time.time(),),
                ).fetchone()[0]
            )
            sanitized = int(
                connection.execute("SELECT COUNT(*) FROM memories WHERE sanitized = 1").fetchone()[0]
            )
            actions = int(connection.execute("SELECT COUNT(*) FROM action_events").fetchone()[0])
        return {
            "ok": True,
            "schema_version": _SCHEMA_VERSION,
            "path": str(self.path),
            "durable_items": total,
            "active_items": active,
            "sanitized_items": sanitized,
            "action_events": actions,
        }

    @classmethod
    def _sanitize_memory_value(
        cls,
        *,
        category: str,
        key: str,
        value: str,
    ) -> tuple[str, bool, str]:
        compact = " ".join(str(value).split()).strip()[:6000]
        probe = f"{category} {key} {compact}".casefold()
        if cls._looks_secret(probe, compact):
            return "[contenu sensible non mémorisé]", True, "secret_redacted"
        if any(marker in probe for marker in _INJECTION_MARKERS):
            return "[instruction non fiable écartée de la mémoire]", True, "prompt_injection_redacted"
        if not compact:
            return "[information vide non mémorisée]", True, "empty_value"
        return compact, False, ""

    @classmethod
    def _looks_secret(cls, probe: str, raw_value: str) -> bool:
        if any(word in probe for word in _SECRET_WORDS):
            return True
        if any(pattern.search(raw_value) for pattern in _SECRET_PATTERNS):
            return True
        digits = re.sub(r"\D", "", raw_value)
        return 13 <= len(digits) <= 19 and cls._passes_luhn(digits)

    @staticmethod
    def _passes_luhn(digits: str) -> bool:
        total = 0
        parity = len(digits) % 2
        for index, char in enumerate(digits):
            value = int(char)
            if index % 2 == parity:
                value *= 2
                if value > 9:
                    value -= 9
            total += value
        return bool(digits) and total % 10 == 0

    @staticmethod
    def _clean_identifier(value: str, max_length: int) -> str:
        compact = " ".join(str(value).split()).strip()
        return compact[:max_length] or "unknown"

    @classmethod
    def _redact_structure(cls, value: Any, *, key_hint: str = "") -> Any:
        if key_hint.casefold() in _SENSITIVE_METADATA_KEYS:
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                str(key)[:120]: cls._redact_structure(item, key_hint=str(key))
                for key, item in list(value.items())[:80]
            }
        if isinstance(value, list):
            return [cls._redact_structure(item) for item in value[:80]]
        if isinstance(value, tuple):
            return [cls._redact_structure(item) for item in value[:80]]
        if isinstance(value, str):
            clean, sanitized, _ = cls._sanitize_memory_value(
                category="metadata",
                key=key_hint or "value",
                value=value,
            )
            return clean if sanitized else clean[:2000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:1000]

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            category=str(row["category"]),
            key=str(row["key"]),
            value=str(row["value"]),
            updated_at=float(row["updated_at"]),
            provenance=str(row["provenance"] or "legacy"),
            confidence=float(row["confidence"] or 0.0),
            expires_at=(float(row["expires_at"]) if row["expires_at"] is not None else None),
            created_at=float(row["created_at"] or row["updated_at"]),
            sanitized=bool(row["sanitized"]),
            reason=str(row["reason"] or ""),
        )


memory_store = MemoryStore(settings.runtime_dir / "jarvis_memory.sqlite3")
