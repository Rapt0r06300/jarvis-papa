from __future__ import annotations

from jarvis_papa.evaluation_lab import evaluation_lab


class ImprovementLab:
    """Compatibility facade over the evidence-gated local evaluation lab."""

    def security_suite(self) -> dict[str, object]:
        return evaluation_lab.run()

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
        baseline = {
            "score": max(0.0, min(float(baseline_success), 1.0)),
            "critical_failures": ["security"] * max(0, int(baseline_security_failures)),
        }
        candidate = {
            "score": max(0.0, min(float(candidate_success), 1.0)),
            "critical_failures": ["security"] * max(0, int(candidate_security_failures)),
        }
        result = evaluation_lab.compare(
            baseline=baseline,
            candidate=candidate,
            candidate_name="candidate",
        )
        latency_ok = True
        if baseline_p95_ms and candidate_p95_ms:
            latency_ok = candidate_p95_ms <= baseline_p95_ms * 1.25
        if not latency_ok:
            result["promotable"] = False
            result["detail"] = "Le candidat est bloqué car la latence p95 régresse trop fortement."
        return {
            **result,
            "promote": bool(result.get("promotable")),
            "requires_human_review": True,
            "latency_ok": latency_ok,
        }


improvement_lab = ImprovementLab()
