from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable
from uuid import uuid4

from jarvis_papa.config import settings
from jarvis_papa.governance import ActionContract


class TransactionState(StrEnum):
    PLANNED = "planned"
    ATTEMPTED = "attempted"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    transaction_id: str
    action_key: str
    contract_digest: str
    reversible: bool
    state: TransactionState
    created_at: float
    updated_at: float
    before: dict[str, object]
    proof: dict[str, object]
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


RollbackHandler = Callable[[TransactionRecord], tuple[bool, str]]


class TransactionJournal:
    """Tamper-evident-ish append journal for action attempts and verified outcomes.

    The journal deliberately stores only bounded metadata/proofs, not mail bodies,
    passwords, prompts or document contents.
    """

    MAX_RECORDS = 1000

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "transactions.jsonl")
        self._lock = threading.Lock()
        self._rollbacks: dict[str, RollbackHandler] = {}

    def register_rollback(self, action_key: str, handler: RollbackHandler) -> None:
        self._rollbacks[action_key.strip()] = handler

    def begin(
        self,
        contract: ActionContract,
        *,
        before: dict[str, object] | None = None,
    ) -> TransactionRecord:
        now = time.time()
        record = TransactionRecord(
            transaction_id=uuid4().hex,
            action_key=contract.action_key,
            contract_digest=contract.digest,
            reversible=contract.reversible,
            state=TransactionState.PLANNED,
            created_at=now,
            updated_at=now,
            before=_bounded_map(before or {}),
            proof={},
        )
        self._append(record)
        return record

    def mark(
        self,
        record: TransactionRecord,
        state: TransactionState,
        *,
        proof: dict[str, object] | None = None,
        error: str = "",
    ) -> TransactionRecord:
        updated = TransactionRecord(
            transaction_id=record.transaction_id,
            action_key=record.action_key,
            contract_digest=record.contract_digest,
            reversible=record.reversible,
            state=state,
            created_at=record.created_at,
            updated_at=time.time(),
            before=record.before,
            proof=_bounded_map(proof or {}),
            error=" ".join(error.split()).strip()[:1000],
        )
        self._append(updated)
        return updated

    def rollback(self, transaction_id: str) -> dict[str, object]:
        record = self.latest(transaction_id)
        if record is None:
            return {"ok": False, "state": "failed", "detail": "Transaction introuvable."}
        if not record.reversible or record.state is not TransactionState.SUCCESS:
            return {
                "ok": False,
                "state": "failed",
                "detail": "Cette transaction n'est pas réversible dans son état actuel.",
            }
        handler = self._rollbacks.get(record.action_key)
        if handler is None:
            return {
                "ok": False,
                "state": "failed",
                "detail": "Aucun rollback vérifié n'est enregistré pour cette action.",
            }
        try:
            ok, detail = handler(record)
        except (OSError, RuntimeError, ValueError) as exc:
            ok, detail = False, f"Rollback impossible ({type(exc).__name__})."
        final = self.mark(
            record,
            TransactionState.ROLLED_BACK if ok else TransactionState.FAILED,
            proof={"rollback_verified": ok},
            error="" if ok else detail,
        )
        return {
            "ok": ok,
            "state": final.state.value,
            "detail": detail,
            "transaction_id": final.transaction_id,
        }

    def latest(self, transaction_id: str) -> TransactionRecord | None:
        records = self._read_all()
        for record in reversed(records):
            if record.transaction_id == transaction_id:
                return record
        return None

    def recent(self, limit: int = 30) -> list[TransactionRecord]:
        return self._read_all()[-max(1, min(int(limit), 100)) :]

    def _append(self, record: TransactionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                return
            self._trim_locked()

    def _trim_locked(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= self.MAX_RECORDS:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text("\n".join(lines[-self.MAX_RECORDS :]) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            temporary.unlink(missing_ok=True)

    def _read_all(self) -> list[TransactionRecord]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[TransactionRecord] = []
        for line in lines[-self.MAX_RECORDS :]:
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    continue
                records.append(
                    TransactionRecord(
                        transaction_id=str(item["transaction_id"]),
                        action_key=str(item["action_key"]),
                        contract_digest=str(item["contract_digest"]),
                        reversible=bool(item.get("reversible")),
                        state=TransactionState(str(item.get("state") or "unknown")),
                        created_at=float(item.get("created_at") or 0.0),
                        updated_at=float(item.get("updated_at") or 0.0),
                        before=_bounded_map(item.get("before") if isinstance(item.get("before"), dict) else {}),
                        proof=_bounded_map(item.get("proof") if isinstance(item.get("proof"), dict) else {}),
                        error=str(item.get("error") or "")[:1000],
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return records


def _bounded_map(payload: dict[str, object]) -> dict[str, object]:
    clean: dict[str, object] = {}
    for key, value in list(payload.items())[:30]:
        name = str(key)[:100]
        if value is None or isinstance(value, (bool, int, float)):
            clean[name] = value
        elif isinstance(value, str):
            clean[name] = value[:1000]
        elif isinstance(value, list):
            clean[name] = [str(item)[:300] for item in value[:20]]
        else:
            clean[name] = str(value)[:1000]
    return clean


transaction_journal = TransactionJournal()
