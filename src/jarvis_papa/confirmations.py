from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    ok: bool
    challenge_id: str | None
    step: int
    required: int
    completed: bool
    expires_at: float | None
    authorization_token: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class _Challenge:
    id: str
    action_key: str
    description: str
    binding_digest: str
    confirmations: int
    expires_at: float


@dataclass(slots=True)
class _Grant:
    token: str
    action_key: str
    binding_digest: str
    expires_at: float


class ConfirmationManager:
    """Two-step, short-lived, one-time authorization bound to exact action parameters."""

    def __init__(
        self,
        *,
        challenge_ttl_seconds: float = 180.0,
        grant_ttl_seconds: float = 90.0,
    ) -> None:
        self.challenge_ttl_seconds = max(1.0, challenge_ttl_seconds)
        self.grant_ttl_seconds = max(1.0, grant_ttl_seconds)
        self._challenges: dict[str, _Challenge] = {}
        self._grants: dict[str, _Grant] = {}
        self._lock = threading.Lock()

    def start(
        self,
        action_key: str,
        description: str,
        binding: dict[str, object] | None = None,
    ) -> ConfirmationResult:
        now = time.time()
        challenge = _Challenge(
            id=secrets.token_urlsafe(24),
            action_key=action_key.strip(),
            description=description.strip(),
            binding_digest=self.binding_digest(binding),
            confirmations=0,
            expires_at=now + self.challenge_ttl_seconds,
        )
        with self._lock:
            self._cleanup_locked(now)
            self._challenges[challenge.id] = challenge
        return ConfirmationResult(
            ok=True,
            challenge_id=challenge.id,
            step=0,
            required=2,
            completed=False,
            expires_at=challenge.expires_at,
            detail="Première autorisation requise.",
        )

    def confirm(self, challenge_id: str) -> ConfirmationResult:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                return ConfirmationResult(
                    ok=False,
                    challenge_id=challenge_id,
                    step=0,
                    required=2,
                    completed=False,
                    expires_at=None,
                    detail="Autorisation expirée ou inconnue.",
                )
            challenge.confirmations += 1
            if challenge.confirmations < 2:
                return ConfirmationResult(
                    ok=True,
                    challenge_id=challenge.id,
                    step=challenge.confirmations,
                    required=2,
                    completed=False,
                    expires_at=challenge.expires_at,
                    detail="Première autorisation enregistrée. Une seconde est obligatoire.",
                )

            self._challenges.pop(challenge.id, None)
            token = secrets.token_urlsafe(32)
            grant = _Grant(
                token=token,
                action_key=challenge.action_key,
                binding_digest=challenge.binding_digest,
                expires_at=now + self.grant_ttl_seconds,
            )
            self._grants[token] = grant
            return ConfirmationResult(
                ok=True,
                challenge_id=challenge.id,
                step=2,
                required=2,
                completed=True,
                expires_at=grant.expires_at,
                authorization_token=token,
                detail="Deux autorisations reçues. Autorisation à usage unique créée.",
            )

    def consume(
        self,
        token: str | None,
        action_key: str,
        binding: dict[str, object] | None = None,
    ) -> bool:
        if not token:
            return False
        now = time.time()
        expected_binding = self.binding_digest(binding)
        with self._lock:
            self._cleanup_locked(now)
            # A presented grant is consumed even on mismatch. This prevents replay/probing.
            grant = self._grants.pop(token, None)
        if grant is None or grant.expires_at < now:
            return False
        if not secrets.compare_digest(grant.action_key, action_key.strip()):
            return False
        return secrets.compare_digest(grant.binding_digest, expected_binding)

    @classmethod
    def binding_digest(cls, binding: dict[str, object] | None) -> str:
        normalized = cls._normalize(binding or {})
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _normalize(cls, value: object) -> object:
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            return format(value, ".12g")
        if isinstance(value, dict):
            return {
                str(key): cls._normalize(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [cls._normalize(item) for item in value]
        return str(value)

    def _cleanup_locked(self, now: float) -> None:
        expired_challenges = [
            key for key, item in self._challenges.items() if item.expires_at < now
        ]
        expired_grants = [key for key, item in self._grants.items() if item.expires_at < now]
        for key in expired_challenges:
            self._challenges.pop(key, None)
        for key in expired_grants:
            self._grants.pop(key, None)


confirmation_manager = ConfirmationManager()
