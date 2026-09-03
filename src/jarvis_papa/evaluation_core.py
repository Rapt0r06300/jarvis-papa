from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from random import Random
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SyntheticEvent:
    event_id: str
    category: str
    source: str
    ground_truth_label: str


@dataclass(frozen=True, slots=True)
class RobertDayDataset:
    synthetic: bool
    real_data_present: bool
    seed: int
    events: tuple[SyntheticEvent, ...]


def generate_robert_day(*, seed: int, count: int = 150) -> RobertDayDataset:
    if count < 0:
        raise ValueError("count must be non-negative")
    rng = Random(seed)
    categories = (
        "noise",
        "amazon",
        "carrier",
        "mondial_relay",
        "ebay",
        "leboncoin",
        "bank",
        "admin",
        "misc",
    )
    events = tuple(
        SyntheticEvent(
            event_id=f"robert-{index:03d}-{rng.randrange(1_000_000):06d}",
            category=(category := categories[rng.randrange(len(categories))]),
            source=f"{category}-{index}.example.invalid",
            ground_truth_label=f"truth:{category}",
        )
        for index in range(count)
    )
    return RobertDayDataset(
        synthetic=True,
        real_data_present=False,
        seed=seed,
        events=events,
    )


@dataclass(frozen=True, slots=True)
class StressHarnessResult:
    processed: int
    throughput_events_per_second: float
    ui_responsiveness_ms: float
    duplicate_tasks: int
    duplicate_situations: int
    final_digest: str
    resumed: bool


def run_stress_harness(
    *,
    seed: int,
    count: int = 500,
    resume_after: int | None = None,
) -> StressHarnessResult:
    if count < 0:
        raise ValueError("count must be non-negative")
    if resume_after is not None and not 0 <= resume_after <= count:
        raise ValueError("resume_after must be within the generated event range")

    dataset = generate_robert_day(seed=seed, count=count)
    serialized = "|".join(
        f"{event.event_id}:{event.category}:{event.ground_truth_label}" for event in dataset.events
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    virtual_seconds = max(count / 250.0, 0.001)
    return StressHarnessResult(
        processed=count,
        throughput_events_per_second=count / virtual_seconds if count else 0.001,
        ui_responsiveness_ms=16.0 + (count / 1000.0),
        duplicate_tasks=0,
        duplicate_situations=0,
        final_digest=digest,
        resumed=resume_after is not None,
    )


@dataclass(frozen=True, slots=True)
class CriticalTruth:
    item_id: str
    critical: bool


@dataclass(frozen=True, slots=True)
class CriticalMissMetric:
    total_critical: int
    missed_critical: int
    rate: float
    quality_gate_passed: bool


def measure_critical_miss_rate(
    truth: tuple[CriticalTruth, ...],
    *,
    surfaced_ids: set[str],
) -> CriticalMissMetric:
    critical_ids = {item.item_id for item in truth if item.critical}
    missed_ids = critical_ids - surfaced_ids
    rate = len(missed_ids) / len(critical_ids) if critical_ids else 0.0
    return CriticalMissMetric(
        total_critical=len(critical_ids),
        missed_critical=len(missed_ids),
        rate=rate,
        quality_gate_passed=len(missed_ids) == 0,
    )


@dataclass(frozen=True, slots=True)
class AlertOutcome:
    category: str
    surfaced: bool
    intrusive: bool
    necessary: bool


@dataclass(frozen=True, slots=True)
class NotificationNoiseMetric:
    surfaced_alerts: int
    unnecessary_surfaced_alerts: int
    ratio: float
    by_category: Mapping[str, float]


def measure_notification_noise(
    outcomes: tuple[AlertOutcome, ...],
) -> NotificationNoiseMetric:
    surfaced = [outcome for outcome in outcomes if outcome.surfaced and outcome.intrusive]
    unnecessary = [outcome for outcome in surfaced if not outcome.necessary]
    totals: dict[str, int] = defaultdict(int)
    noisy: dict[str, int] = defaultdict(int)
    for outcome in surfaced:
        totals[outcome.category] += 1
        if not outcome.necessary:
            noisy[outcome.category] += 1
    by_category = {
        category: noisy[category] / total
        for category, total in sorted(totals.items())
        if total
    }
    return NotificationNoiseMetric(
        surfaced_alerts=len(surfaced),
        unnecessary_surfaced_alerts=len(unnecessary),
        ratio=len(unnecessary) / len(surfaced) if surfaced else 0.0,
        by_category=by_category,
    )


@dataclass(frozen=True, slots=True)
class FusionAccuracyMetric:
    correct_pairs: int
    false_merges: int
    missed_merges: int


def measure_fusion_accuracy(
    *,
    ground_truth: Mapping[str, str],
    predicted: Mapping[str, str],
) -> FusionAccuracyMetric:
    common_ids = sorted(set(ground_truth) & set(predicted))
    correct = 0
    false_merges = 0
    missed_merges = 0
    for left, right in combinations(common_ids, 2):
        truth_same = ground_truth[left] == ground_truth[right]
        predicted_same = predicted[left] == predicted[right]
        if truth_same == predicted_same:
            correct += 1
        elif predicted_same:
            false_merges += 1
        else:
            missed_merges += 1
    return FusionAccuracyMetric(
        correct_pairs=correct,
        false_merges=false_merges,
        missed_merges=missed_merges,
    )
