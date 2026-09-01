from dataclasses import dataclass
from enum import StrEnum


class ActionRisk(StrEnum):
    """Risk level attached to an action Jarvis wants to perform."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True, slots=True)
class ActionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str
    confirmations_required: int = 0
    confirmations_received: int = 0

    @property
    def confirmations_remaining(self) -> int:
        return max(0, self.confirmations_required - self.confirmations_received)


class SecurityPolicy:
    """Deny any real modification until Robert has explicitly confirmed it twice."""

    SENSITIVE_CONFIRMATIONS = 2

    def evaluate(
        self,
        risk: ActionRisk,
        *,
        confirmations: int = 0,
        confirmed: bool = False,
    ) -> ActionDecision:
        if risk is ActionRisk.READ:
            return ActionDecision(
                allowed=True,
                requires_confirmation=False,
                reason="Lecture autorisée : aucune modification n'est effectuée.",
            )

        received = max(0, int(confirmations))
        # Compatibility with older callers: a boolean confirmation counts as one, never two.
        if confirmed:
            received = max(received, 1)

        if received >= self.SENSITIVE_CONFIRMATIONS:
            return ActionDecision(
                allowed=True,
                requires_confirmation=True,
                reason="Action sensible autorisée après deux confirmations explicites de Robert.",
                confirmations_required=self.SENSITIVE_CONFIRMATIONS,
                confirmations_received=received,
            )

        remaining = self.SENSITIVE_CONFIRMATIONS - received
        if received == 0:
            reason = (
                "Action sensible bloquée. Robert doit confirmer une première fois, puis confirmer "
                "une seconde fois avant toute modification réelle."
            )
        else:
            reason = "Première confirmation reçue. Une seconde confirmation explicite est obligatoire."

        return ActionDecision(
            allowed=False,
            requires_confirmation=True,
            reason=reason,
            confirmations_required=self.SENSITIVE_CONFIRMATIONS,
            confirmations_received=received,
        )


security_policy = SecurityPolicy()
