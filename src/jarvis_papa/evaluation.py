from __future__ import annotations

from dataclasses import asdict, dataclass

from jarvis_papa.governance import ActionContract, PolicyVerdict, RiskLevel, policy_kernel


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    category: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ImprovementLab:
    """Offline regression gate. It proposes/promotes nothing automatically."""

    def security_suite(self) -> dict[str, object]:
        cases: list[EvaluationCase] = []
        safe_read = ActionContract.create(
            action_key="files.search",
            description="Chercher un document autorisé.",
            risk=RiskLevel.SAFE,
            read_only=True,
        )
        result = policy_kernel.evaluate(safe_read)
        cases.append(
            EvaluationCase(
                "safe_read_allowed",
                "security",
                result.verdict is PolicyVerdict.ALLOW,
                result.reason,
            )
        )

        mutation = ActionContract.create(
            action_key="mail.send_reply",
            description="Envoyer un mail.",
            binding={"recipient": "example.invalid", "draft": "digest"},
            risk=RiskLevel.HIGH,
            read_only=False,
            expected_proof=("verified", "mode=sendNow"),
        )
        result = policy_kernel.evaluate(mutation, authorization_present=False, source="mail")
        cases.append(
            EvaluationCase(
                "mutation_requires_confirmation",
                "security",
                result.verdict is PolicyVerdict.REQUIRE_CONFIRMATION,
                result.reason,
            )
        )
        result = policy_kernel.evaluate(mutation, authorization_present=True, source="mail")
        cases.append(
            EvaluationCase(
                "authorized_mutation_allowed",
                "security",
                result.verdict is PolicyVerdict.ALLOW,
                result.reason,
            )
        )

        expired = ActionContract(
            action_key="mail.send_reply",
            description="Expiré",
            binding={},
            risk=RiskLevel.HIGH,
            read_only=False,
            created_at=1.0,
            expires_at=2.0,
        )
        result = policy_kernel.evaluate(expired, authorization_present=True)
        cases.append(
            EvaluationCase(
                "expired_contract_denied",
                "security",
                result.verdict is PolicyVerdict.DENY,
                result.reason,
            )
        )
        return self._summary(cases)

    @staticmethod
    def compare_candidate(
        *,
        baseline_success: float,
        candidate_success: float,
        baseline_security_failures: int,
        candidate_security_failures: int,
        baseline_p95_ms: float | None = None,
        candidate_p95_ms: float | None = None,
    ) -> dict[str, object]:
        no_security_regression = candidate_security_failures <= baseline_security_failures
        success_improved = candidate_success > baseline_success
        latency_ok = True
        if baseline_p95_ms and candidate_p95_ms:
            latency_ok = candidate_p95_ms <= baseline_p95_ms * 1.25
        promote = no_security_regression and success_improved and latency_ok
        return {
            "promote": promote,
            "requires_human_review": True,
            "no_security_regression": no_security_regression,
            "success_improved": success_improved,
            "latency_ok": latency_ok,
            "detail": (
                "Candidat éligible à une revue humaine. Aucun déploiement automatique."
                if promote
                else "Candidat rejeté : il ne bat pas suffisamment la version actuelle."
            ),
        }

    @staticmethod
    def _summary(cases: list[EvaluationCase]) -> dict[str, object]:
        passed = sum(item.passed for item in cases)
        return {
            "ok": passed == len(cases),
            "passed": passed,
            "total": len(cases),
            "score": round(passed / len(cases), 4) if cases else 0.0,
            "cases": [item.to_dict() for item in cases],
            "promotion_policy": "benchmark_then_human_review_never_auto_deploy",
        }


improvement_lab = ImprovementLab()
