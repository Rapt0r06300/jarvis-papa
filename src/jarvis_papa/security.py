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


class SecurityPolicy:
    """Deny sensitive actions unless the user has explicitly confirmed them."""

    def evaluate(self, risk: ActionRisk, *, confirmed: bool = False) -> ActionDecision:
        if risk is ActionRisk.READ:
            return ActionDecision(
                allowed=True,
                requires_confirmation=False,
                reason="Lecture autorisée : aucune modification n'est effectuée.",
            )

        if confirmed:
            return ActionDecision(
                allowed=True,
                requires_confirmation=True,
                reason="Action sensible autorisée après confirmation explicite.",
            )

        if risk is ActionRisk.DESTRUCTIVE:
            reason = "Action destructive bloquée tant qu'elle n'est pas confirmée explicitement."
        else:
            reason = "Modification bloquée tant qu'elle n'est pas confirmée."

        return ActionDecision(
            allowed=False,
            requires_confirmation=True,
            reason=reason,
        )


security_policy = SecurityPolicy()
