from __future__ import annotations

from dataclasses import dataclass

from jarvis_papa.audit import audit_log
from jarvis_papa.confirmations import confirmation_manager
from jarvis_papa.governance import ActionContract, PolicyVerdict, RiskLevel, policy_kernel


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    ok: bool
    contract: ActionContract
    reason: str


class AuthorizationGate:
    """Single mutation seam: contract -> policy -> exact two-step grant -> audit."""

    def authorize(
        self,
        *,
        token: str,
        action_key: str,
        description: str,
        binding: dict[str, object],
        risk: RiskLevel = RiskLevel.MEDIUM,
        source: str = "local",
        expected_proof: tuple[str, ...] = (),
        reversible: bool = False,
    ) -> AuthorizationDecision:
        contract = ActionContract.create(
            action_key=action_key,
            description=description,
            binding=binding,
            risk=risk,
            read_only=False,
            expected_proof=expected_proof,
            reversible=reversible,
        )
        policy = policy_kernel.evaluate(
            contract,
            authorization_present=bool(token),
            source=source,
        )
        if policy.verdict is not PolicyVerdict.ALLOW:
            audit_log.record(
                "policy_denied",
                action=action_key,
                ok=False,
                metadata={
                    "contract_digest": contract.digest,
                    "verdict": policy.verdict.value,
                    "source": source,
                },
            )
            return AuthorizationDecision(False, contract, policy.reason)

        consumed = confirmation_manager.consume(token, action_key, binding)
        audit_log.record(
            "authorization_consumed",
            action=action_key,
            ok=consumed,
            metadata={
                "contract_digest": contract.digest,
                "binding_keys": sorted(binding),
                "source": source,
            },
        )
        if not consumed:
            return AuthorizationDecision(
                False,
                contract,
                "La double autorisation exacte est absente, expirée ou déjà utilisée.",
            )
        return AuthorizationDecision(True, contract, "Autorisation et politique validées.")


authorization_gate = AuthorizationGate()
