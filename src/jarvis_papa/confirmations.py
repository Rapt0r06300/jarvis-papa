from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    ok: bool
    challenge_id: str | None = None
    step: int = 0
    completed: bool = False
    authorization_token: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "challenge_id": self.challenge_id,
            "step": self.step,
            "completed": self.completed,
            "authorization_token": self.authorization_token,
            "reason": self.reason,
        }


@dataclass(slots=True)
class _Challenge:
    id: str
    action_key: str
    description: str
    confirmations: int
    expires_at: float


@dataclass(slots=True)
class _Grant:
    token: str
    action_key: str
    expires_at: float


class ConfirmationManager:
    """Require two distinct server-side confirmations before a sensitive action.

    A caller cannot authorize an operation by merely posting ``confirmations=2``.
    It must create a short-lived challenge, confirm it twice, then present the
    resulting one-time grant to the exact action family.
    """

    def __init__(self, *, challenge_ttl_seconds: int = 180, grant_ttl_seconds: int = 90) -> None:
        self.challenge_ttl_seconds = challenge_ttl_seconds
        self.grant_ttl_seconds = grant_ttl_seconds
        self._challenges: dict[str, _Challenge] = {}
        self._grants: dict[str, _Grant] = {}
        self._lock = Lock()

    def start(self, action_key: str, description: str) -> ConfirmationResult:
        action_key = action_key.strip()
        description = " ".join(description.split()).strip()
        if not action_key or not description:
            return ConfirmationResult(False, reason="Action de confirmation invalide.")
        now = time.time()
        challenge = _Challenge(
            id=secrets.token_urlsafe(24),
            action_key=action_key,
            description=description[:500],
            confirmations=0,
            expires_at=now + self.challenge_ttl_seconds,
        )
        with self._lock:
            self._cleanup_locked(now)
            self._challenges[challenge.id] = challenge
        return ConfirmationResult(
            True,
            challenge_id=challenge.id,
            step=0,
            reason="Première autorisation requise.",
        )

    def confirm(self, challenge_id: str) -> ConfirmationResult:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                return ConfirmationResult(False, reason="Confirmation expirée ou inconnue.")
            challenge.confirmations += 1
            if challenge.confirmations < 2:
                return ConfirmationResult(
                    True,
                    challenge_id=challenge.id,
                    step=1,
                    reason="Première autorisation enregistrée. Une seconde est obligatoire.",
                )

            token = secrets.token_urlsafe(32)
            self._grants[token] = _Grant(
                token=token,
                action_key=challenge.action_key,
                expires_at=now + self.grant_ttl_seconds,
            )
            self._challenges.pop(challenge.id, None)
            return ConfirmationResult(
                True,
                challenge_id=challenge.id,
                step=2,
                completed=True,
                authorization_token=token,
                reason="Deux autorisations reçues. Autorisation valable une seule fois.",
            )

    def consume(self, token: str, action_key: str) -> bool:
        if not token:
            return False
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            grant = self._grants.pop(token, None)
            return bool(grant and grant.action_key == action_key and grant.expires_at >= now)

    def _cleanup_locked(self, now: float) -> None:
        for challenge_id in [
            key for key, value in self._challenges.items() if value.expires_at < now
        ]:
            self._challenges.pop(challenge_id, None)
        for token in [key for key, value in self._grants.items() if value.expires_at < now]:
            self._grants.pop(token, None)


confirmation_manager = ConfirmationManager()
