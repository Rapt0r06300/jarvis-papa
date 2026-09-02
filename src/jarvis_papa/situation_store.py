from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from jarvis_papa.config import settings
from jarvis_papa.situations import (
    ActionState,
    EntityRef,
    NormalizedEvent,
    SearchResult,
    Situation,
    SituationStatus,
)


class SituationStore:
    """Versioned local store for Robert Autopilot events and situations.

    The database lives under runtime so the existing BackupManager includes it
    automatically. Older Jarvis builds ignore this separate file, which makes
    rollback safe: no existing 0.7.0 state is overwritten or reinterpreted.
    """

    SCHEMA_VERSION = 3

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "situations.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def schema_version(self) -> int:
        with sqlite3.connect(self.path, timeout=5) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def migration_info(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version(),
            "database": str(self.path),
            "backup_compatible": True,
            "rollback_policy": "older_build_ignores_separate_situation_database",
            "idempotent_migrations": True,
            "checkpoint_lanes": ("live", "backfill"),
            "crash_replay": "unprocessed_events_are_replayed_until_marked_processed",
        }

    def ingest_event(self, event: NormalizedEvent) -> bool:
        payload = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    identity_key, source, source_event_id, event_type,
                    occurred_at, observed_at, payload_json, created_at,
                    processed_at, processing_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, '')
                """,
                (
                    event.identity_key,
                    event.source,
                    event.source_event_id,
                    event.event_type,
                    event.occurred_at,
                    event.observed_at,
                    payload,
                    time.time(),
                ),
            )
        return bool(cursor.rowcount)

    def event_processed(self, identity_key: str) -> bool:
        with sqlite3.connect(self.path, timeout=5) as connection:
            row = connection.execute(
                "SELECT processed_at FROM events WHERE identity_key=? LIMIT 1",
                (identity_key,),
            ).fetchone()
        return bool(row and row[0] is not None)

    def mark_event_processed(self, identity_key: str) -> None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                "UPDATE events SET processed_at=?, processing_error='' WHERE identity_key=?",
                (time.time(), identity_key),
            )

    def mark_event_error(self, identity_key: str, error: str) -> None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                "UPDATE events SET processed_at=NULL, processing_error=? WHERE identity_key=?",
                (" ".join(error.split()).strip()[:1000], identity_key),
            )

    def get_event(self, identity_key: str) -> NormalizedEvent | None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            row = connection.execute(
                "SELECT payload_json FROM events WHERE identity_key=? LIMIT 1",
                (identity_key,),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(str(row[0]))
        except json.JSONDecodeError:
            return None
        return NormalizedEvent.from_dict(payload) if isinstance(payload, dict) else None

    def save_entity(self, entity: EntityRef) -> None:
        payload = json.dumps(entity.to_dict(), ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                """
                INSERT INTO entities(entity_id, kind, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    kind=excluded.kind,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (entity.entity_id, entity.kind.value, payload, time.time()),
            )

    def get_entity(self, entity_id: str) -> EntityRef | None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            row = connection.execute(
                "SELECT payload_json FROM entities WHERE entity_id=? LIMIT 1",
                (entity_id,),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(str(row[0]))
        except json.JSONDecodeError:
            return None
        return EntityRef.from_dict(payload) if isinstance(payload, dict) else None

    def save_situation(
        self,
        situation: Situation,
        *,
        correlation_keys: tuple[str, ...] | list[str] = (),
    ) -> None:
        payload = json.dumps(situation.to_dict(), ensure_ascii=False, sort_keys=True)
        now = time.time()
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO situations(
                    situation_id, domain, title, status, state, confidence,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(situation_id) DO UPDATE SET
                    domain=excluded.domain,
                    title=excluded.title,
                    status=excluded.status,
                    state=excluded.state,
                    confidence=excluded.confidence,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    situation.situation_id,
                    situation.domain.value,
                    situation.title,
                    situation.status.value,
                    situation.state,
                    situation.confidence,
                    payload,
                    situation.created_at,
                    max(now, situation.updated_at),
                ),
            )
            for priority, key in enumerate(correlation_keys):
                clean = str(key).strip()[:200]
                if not clean:
                    continue
                existing = connection.execute(
                    "SELECT situation_id FROM correlation_keys WHERE key=? LIMIT 1",
                    (clean,),
                ).fetchone()
                if existing and str(existing[0]) != situation.situation_id:
                    raise ValueError("correlation key collision between situations")
                connection.execute(
                    """
                    INSERT INTO correlation_keys(key, situation_id, priority, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        priority=MIN(correlation_keys.priority, excluded.priority)
                    """,
                    (clean, situation.situation_id, priority, now),
                )

    def get_situation(self, situation_id: str) -> Situation | None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            row = connection.execute(
                "SELECT payload_json FROM situations WHERE situation_id=? LIMIT 1",
                (situation_id,),
            ).fetchone()
        return self._situation_from_row(row)

    def find_situation_by_keys(self, keys: tuple[str, ...] | list[str]) -> Situation | None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            for key in keys:
                row = connection.execute(
                    """
                    SELECT s.payload_json
                    FROM correlation_keys AS k
                    JOIN situations AS s ON s.situation_id=k.situation_id
                    WHERE k.key=?
                    LIMIT 1
                    """,
                    (str(key)[:200],),
                ).fetchone()
                situation = self._situation_from_row(row)
                if situation is not None:
                    return situation
        return None

    def list_situations(self, *, limit: int = 100) -> list[Situation]:
        with sqlite3.connect(self.path, timeout=5) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM situations ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        output: list[Situation] = []
        for row in rows:
            situation = self._situation_from_row(row)
            if situation is not None:
                output.append(situation)
        return output

    def checkpoint(
        self,
        source: str,
        cursor: str,
        *,
        lane: str = "live",
        source_version: str = "",
        evidence_hash: str = "",
    ) -> None:
        clean_source = " ".join(source.split()).strip()[:80]
        clean_lane = " ".join(lane.casefold().split()).strip()[:40]
        if not clean_source or clean_lane not in {"live", "backfill"}:
            raise ValueError("checkpoint requires source and a live/backfill lane")
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO checkpoints(
                    source, lane, cursor, source_version, evidence_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, lane) DO UPDATE SET
                    cursor=excluded.cursor,
                    source_version=excluded.source_version,
                    evidence_hash=excluded.evidence_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    clean_source,
                    clean_lane,
                    str(cursor)[:1000],
                    str(source_version)[:120],
                    str(evidence_hash)[:128],
                    time.time(),
                ),
            )

    def get_checkpoint(self, source: str, *, lane: str = "live") -> dict[str, object] | None:
        clean_source = " ".join(source.split()).strip()[:80]
        clean_lane = " ".join(lane.casefold().split()).strip()[:40]
        if clean_lane not in {"live", "backfill"}:
            raise ValueError("checkpoint lane must be live or backfill")
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT source, lane, cursor, source_version, evidence_hash, updated_at
                FROM checkpoints WHERE source=? AND lane=? LIMIT 1
                """,
                (clean_source, clean_lane),
            ).fetchone()
        return dict(row) if row is not None else None

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        tokens = {
            token.casefold()
            for token in " ".join(str(query).split()).split(" ")
            if len(token) >= 2
        }
        if not tokens:
            return []
        action_query = bool(
            tokens
            & {
                "faire",
                "répondre",
                "repondre",
                "action",
                "urgent",
                "retirer",
                "payer",
                "vérifier",
                "verifier",
                "relancer",
            }
        )
        results: list[SearchResult] = []
        for situation in self.list_situations(limit=300):
            timeline = " ".join(item.summary for item in situation.timeline[-12:])
            haystack = (
                f"{situation.title} {situation.domain.value} {situation.state} "
                f"{timeline} {' '.join(situation.entity_ids)}"
            )
            score = self._token_score(tokens, haystack)
            if score <= 0:
                continue
            if situation.status is SituationStatus.ACTIVE:
                score += 0.15
            elif situation.status in {SituationStatus.COMPLETED, SituationStatus.ARCHIVED}:
                score -= 0.25 if action_query else 0.08
            if situation.action_state not in {ActionState.NO_ACTION, ActionState.READ_ONLY}:
                score += 0.12 if action_query else 0.03
            provenance = tuple(
                f"{item.source}:{item.source_id}" for item in situation.evidence[-8:]
            )
            results.append(
                SearchResult(
                    result_type="situation",
                    object_id=situation.situation_id,
                    title=situation.title,
                    snippet=timeline[-700:] or situation.state,
                    score=round(max(0.0, score), 4),
                    provenance=provenance,
                )
            )

        with sqlite3.connect(self.path, timeout=5) as connection:
            rows = connection.execute(
                "SELECT entity_id, payload_json FROM entities ORDER BY updated_at DESC LIMIT 500"
            ).fetchall()
        for entity_id, raw_payload in rows:
            try:
                payload = json.loads(str(raw_payload))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            entity = EntityRef.from_dict(payload)
            haystack = f"{entity.kind.value} {entity.canonical_id} {' '.join(entity.aliases)}"
            score = self._token_score(tokens, haystack)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    result_type="entity",
                    object_id=str(entity_id),
                    title=entity.canonical_id,
                    snippet=f"{entity.kind.value} · {' · '.join(entity.aliases[:3])}",
                    score=score,
                    provenance=tuple(
                        f"{item.source}:{item.source_id}" for item in entity.provenance[-8:]
                    ),
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[: max(1, min(int(limit), 50))]

    def stats(self) -> dict[str, int]:
        with sqlite3.connect(self.path, timeout=5) as connection:
            return {
                "schema_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
                "events": int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
                "entities": int(connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]),
                "situations": int(connection.execute("SELECT COUNT(*) FROM situations").fetchone()[0]),
                "checkpoints": int(connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]),
            }

    @staticmethod
    def _token_score(tokens: set[str], haystack: str) -> float:
        folded = haystack.casefold()
        matches = sum(token in folded for token in tokens)
        if not matches:
            return 0.0
        exact = " ".join(sorted(tokens)) in folded
        return round(matches / len(tokens) + (0.25 if exact else 0.0), 4)

    @staticmethod
    def _situation_from_row(row: tuple[object, ...] | None) -> Situation | None:
        if not row:
            return None
        try:
            payload = json.loads(str(row[0]))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return Situation.from_dict(payload)
        except (TypeError, ValueError):
            return None

    def _migrate(self) -> None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > self.SCHEMA_VERSION:
                raise RuntimeError("situation database is newer than this Jarvis build")
            if current == 0:
                self._create_schema_v3(connection)
                for version in range(1, self.SCHEMA_VERSION + 1):
                    self._record_migration(connection, version)
                connection.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
                return
            if current == 1:
                connection.executescript(
                    """
                    ALTER TABLE checkpoints RENAME TO checkpoints_v1;
                    CREATE TABLE checkpoints(
                        source TEXT NOT NULL,
                        lane TEXT NOT NULL DEFAULT 'live',
                        cursor TEXT NOT NULL,
                        source_version TEXT NOT NULL,
                        evidence_hash TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY(source, lane)
                    );
                    INSERT INTO checkpoints(
                        source, lane, cursor, source_version, evidence_hash, updated_at
                    )
                    SELECT source, 'live', cursor, source_version, evidence_hash, updated_at
                    FROM checkpoints_v1;
                    DROP TABLE checkpoints_v1;
                    """
                )
                self._record_migration(connection, 2)
                connection.execute("PRAGMA user_version=2")
                current = 2
            if current == 2:
                connection.execute("ALTER TABLE events ADD COLUMN processed_at REAL")
                connection.execute(
                    "ALTER TABLE events ADD COLUMN processing_error TEXT NOT NULL DEFAULT ''"
                )
                self._record_migration(connection, 3)
                connection.execute("PRAGMA user_version=3")

    @staticmethod
    def _create_schema_v3(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS migration_history(
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
                identity_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at REAL NOT NULL,
                observed_at REAL NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                processed_at REAL,
                processing_error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS events_source_observed
                ON events(source, observed_at DESC);
            CREATE TABLE IF NOT EXISTS entities(
                entity_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS situations(
                situation_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                state TEXT NOT NULL,
                confidence REAL NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS situations_updated
                ON situations(updated_at DESC);
            CREATE TABLE IF NOT EXISTS correlation_keys(
                key TEXT PRIMARY KEY,
                situation_id TEXT NOT NULL,
                priority INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(situation_id) REFERENCES situations(situation_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS correlation_situation
                ON correlation_keys(situation_id, priority);
            CREATE TABLE IF NOT EXISTS checkpoints(
                source TEXT NOT NULL,
                lane TEXT NOT NULL DEFAULT 'live',
                cursor TEXT NOT NULL,
                source_version TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(source, lane)
            );
            """
        )

    @staticmethod
    def _record_migration(connection: sqlite3.Connection, version: int) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO migration_history(version, applied_at) VALUES (?, ?)",
            (version, time.time()),
        )


situation_store = SituationStore()
