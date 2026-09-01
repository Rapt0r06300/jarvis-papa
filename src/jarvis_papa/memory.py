import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class MemoryItem:
    category: str
    key: str
    value: str
    updated_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Habit:
    action: str
    target: str
    count: int
    last_seen: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MemoryStore:
    """Local SQLite memory for preferences, useful facts and repeated actions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
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
                """
            )

    def remember(self, category: str, key: str, value: str) -> MemoryItem:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories(category, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(category, key)
                DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (category.strip(), key.strip(), value.strip(), now),
            )
        return MemoryItem(category.strip(), key.strip(), value.strip(), now)

    def recall(self, query: str, limit: int = 8) -> list[MemoryItem]:
        tokens = [token.lower() for token in query.split() if len(token) >= 3][:8]
        if not tokens:
            return []
        clauses = []
        params: list[object] = []
        for token in tokens:
            clauses.append("(lower(key) LIKE ? OR lower(value) LIKE ? OR lower(category) LIKE ?)")
            pattern = f"%{token}%"
            params.extend((pattern, pattern, pattern))
        params.append(limit)
        sql = (
            "SELECT category, key, value, updated_at FROM memories WHERE "
            + " OR ".join(clauses)
            + " ORDER BY updated_at DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [MemoryItem(row["category"], row["key"], row["value"], row["updated_at"]) for row in rows]

    def record_action(
        self,
        action: str,
        target: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO action_events(action, target, metadata, created_at) VALUES (?, ?, ?, ?)",
                (
                    action.strip(),
                    target.strip()[:1000],
                    json.dumps(metadata or {}, ensure_ascii=False),
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
                (min_count, limit),
            ).fetchall()
        return [Habit(row["action"], row["target"], row["count"], row["last_seen"]) for row in rows]

    def context_for(self, query: str, limit: int = 6) -> str:
        items = self.recall(query, limit=limit)
        if not items:
            return ""
        return "\n".join(f"- {item.category}/{item.key}: {item.value}" for item in items)


memory_store = MemoryStore(settings.runtime_dir / "jarvis_memory.sqlite3")
