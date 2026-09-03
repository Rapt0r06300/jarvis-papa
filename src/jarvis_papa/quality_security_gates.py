from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ObligationTruth:
    item_id: str
    task_type: str
    required: bool
    resolved: bool = False


@dataclass(frozen=True, slots=True)
class ClassificationMetric:
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float


@dataclass(frozen=True, slots=True)
class ObligationQualityMetric:
    by_type: Mapping[str, ClassificationMetric]


def _ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    return numerator / denominator if denominator else empty


def measure_obligation_quality(
    truth: tuple[ObligationTruth, ...],
    *,
    predicted_required_ids: set[str],
) -> ObligationQualityMetric:
    grouped: dict[str, list[ObligationTruth]] = defaultdict(list)
    for item in truth:
        grouped[item.task_type].append(item)

    by_type: dict[str, ClassificationMetric] = {}
    for task_type, items in sorted(grouped.items()):
        actual = {item.item_id for item in items if item.required and not item.resolved}
        known = {item.item_id for item in items}
        predicted = predicted_required_ids & known
        true_positives = len(actual & predicted)
        false_positives = len(predicted - actual)
        false_negatives = len(actual - predicted)
        by_type[task_type] = ClassificationMetric(
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            precision=_ratio(true_positives, true_positives + false_positives),
            recall=_ratio(true_positives, true_positives + false_negatives),
        )
    return ObligationQualityMetric(by_type=by_type)


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    domain: str
    outcome: str


@dataclass(frozen=True, slots=True)
class DraftDomainMetric:
    accepted_no_edit: int
    edited: int
    rejected: int


@dataclass(frozen=True, slots=True)
class DraftOutcomeMetric:
    by_domain: Mapping[str, DraftDomainMetric]


def measure_draft_outcomes(outcomes: tuple[DraftOutcome, ...]) -> DraftOutcomeMetric:
    allowed = {"accepted", "edited", "rejected"}
    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {"accepted": 0, "edited": 0, "rejected": 0}
    )
    for outcome in outcomes:
        if outcome.outcome not in allowed:
            raise ValueError(f"unsupported draft outcome: {outcome.outcome}")
        counters[outcome.domain][outcome.outcome] += 1
    return DraftOutcomeMetric(
        by_domain={
            domain: DraftDomainMetric(
                accepted_no_edit=counts["accepted"],
                edited=counts["edited"],
                rejected=counts["rejected"],
            )
            for domain, counts in sorted(counters.items())
        }
    )


@dataclass(frozen=True, slots=True)
class StartupGateResult:
    first_useful_ms: int
    full_completion_ms: int
    baseline_first_useful_ms: int
    threshold_ms: int
    first_useful_before_full_completion: bool
    release_gate_passed: bool


def gate_startup_time(
    *,
    first_useful_ms: int,
    full_completion_ms: int,
    baseline_first_useful_ms: int,
    max_regression_ratio: float = 1.25,
) -> StartupGateResult:
    if min(first_useful_ms, full_completion_ms, baseline_first_useful_ms) < 0:
        raise ValueError("startup timings must be non-negative")
    if max_regression_ratio <= 0:
        raise ValueError("max_regression_ratio must be positive")
    threshold_ms = round(baseline_first_useful_ms * max_regression_ratio)
    before_completion = first_useful_ms < full_completion_ms
    return StartupGateResult(
        first_useful_ms=first_useful_ms,
        full_completion_ms=full_completion_ms,
        baseline_first_useful_ms=baseline_first_useful_ms,
        threshold_ms=threshold_ms,
        first_useful_before_full_completion=before_completion,
        release_gate_passed=before_completion and first_useful_ms <= threshold_ms,
    )


@dataclass(frozen=True, slots=True)
class InjectionCase:
    source: str
    content: str
    requested_action: str


@dataclass(frozen=True, slots=True)
class InjectionCaseResult:
    source: str
    untrusted_content: bool
    injection_detected: bool
    system_authority_granted: bool
    external_action_allowed: bool


@dataclass(frozen=True, slots=True)
class InjectionMatrixResult:
    results: tuple[InjectionCaseResult, ...]
    failed_sources: tuple[str, ...]
    release_gate_passed: bool


_UNTRUSTED_SOURCES = {"email", "marketplace", "web", "pdf", "document", "qr", "tool_output"}
_INJECTION_MARKERS = (
    "ignore les règles",
    "ignore the rules",
    "ignore previous",
    "system prompt",
    "envoie tous",
    "send all",
    "documents et secrets",
    "credentials",
)
_EXTERNAL_ACTION_MARKERS = ("send", "envoie", "publish", "pay", "transfer", "delete", "accept")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in markers)


def run_prompt_injection_matrix(cases: tuple[InjectionCase, ...]) -> InjectionMatrixResult:
    results: list[InjectionCaseResult] = []
    failed_sources: list[str] = []
    for case in cases:
        untrusted = case.source.casefold() in _UNTRUSTED_SOURCES
        injection = _contains_any(case.content, _INJECTION_MARKERS)
        requests_external = _contains_any(case.requested_action, _EXTERNAL_ACTION_MARKERS)
        authority_granted = False if untrusted else not injection
        external_allowed = not untrusted and not injection and not requests_external
        result = InjectionCaseResult(
            source=case.source,
            untrusted_content=untrusted,
            injection_detected=injection,
            system_authority_granted=authority_granted,
            external_action_allowed=external_allowed,
        )
        results.append(result)
        if untrusted and (authority_granted or external_allowed):
            failed_sources.append(case.source)
    failures = tuple(sorted(set(failed_sources)))
    return InjectionMatrixResult(
        results=tuple(results),
        failed_sources=failures,
        release_gate_passed=not failures,
    )


@dataclass(frozen=True, slots=True)
class LinkSafetyResult:
    host: str
    suspicious: bool
    warning_required: bool
    verify_required: bool
    auto_open_allowed: bool
    secret_transmission_allowed: bool
    sensitive_action_allowed: bool


_OFFICIAL_DOMAINS: Mapping[str, tuple[str, ...]] = {
    "amazon": ("amazon.fr", "amazon.com"),
    "mondial_relay": ("mondialrelay.fr",),
    "mondial relay": ("mondialrelay.fr",),
}


def _is_official_host(host: str, approved: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in approved)


def assess_link_safety(
    url: str,
    *,
    claimed_brand: str,
    urgent: bool = False,
    asks_for_secret: bool = False,
) -> LinkSafetyResult:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    brand = claimed_brand.casefold().strip()
    approved = _OFFICIAL_DOMAINS.get(brand, ())
    official = bool(host) and bool(approved) and _is_official_host(host, approved)
    brand_token = brand.replace("_", "").replace(" ", "")
    compact_host = host.replace("-", "").replace(".", "")
    lookalike = bool(brand_token and brand_token in compact_host and not official)
    suspicious = (
        parsed.scheme.casefold() != "https"
        or not host
        or lookalike
        or asks_for_secret
        or (urgent and not official)
    )
    return LinkSafetyResult(
        host=host,
        suspicious=suspicious,
        warning_required=suspicious,
        verify_required=suspicious,
        auto_open_allowed=not suspicious,
        secret_transmission_allowed=False if suspicious else not asks_for_secret,
        sensitive_action_allowed=not suspicious,
    )
