from __future__ import annotations


def test_p10_01_seeded_robert_day_is_reproducible_and_contains_no_real_data() -> None:
    from jarvis_papa.evaluation_core import generate_robert_day

    first = generate_robert_day(seed=2026, count=150)
    second = generate_robert_day(seed=2026, count=150)

    assert first == second
    assert len(first.events) == 150
    assert first.synthetic is True
    assert first.real_data_present is False
    assert all(event.source.endswith(".example.invalid") for event in first.events)
    assert all(event.ground_truth_label for event in first.events)


def test_p10_02_500_event_stress_resume_is_deterministic_and_duplicate_free() -> None:
    from jarvis_papa.evaluation_core import run_stress_harness

    uninterrupted = run_stress_harness(seed=7, count=500)
    resumed = run_stress_harness(seed=7, count=500, resume_after=250)

    assert uninterrupted.final_digest == resumed.final_digest
    assert resumed.processed == 500
    assert resumed.duplicate_tasks == 0
    assert resumed.duplicate_situations == 0
    assert resumed.throughput_events_per_second > 0
    assert resumed.ui_responsiveness_ms > 0


def test_p10_03_critical_miss_rate_counts_each_missed_critical_item_once_and_fails_gate() -> None:
    from jarvis_papa.evaluation_core import CriticalTruth, measure_critical_miss_rate

    truth = (
        CriticalTruth("bank-1", True),
        CriticalTruth("pickup-1", True),
        CriticalTruth("newsletter-1", False),
    )
    metric = measure_critical_miss_rate(truth, surfaced_ids={"bank-1"})

    assert metric.total_critical == 2
    assert metric.missed_critical == 1
    assert metric.rate == 0.5
    assert metric.quality_gate_passed is False


def test_p10_04_noise_ratio_counts_intrusive_unnecessary_alerts_not_silent_briefing_entries() -> None:
    from jarvis_papa.evaluation_core import AlertOutcome, measure_notification_noise

    outcomes = (
        AlertOutcome("newsletter", surfaced=True, intrusive=True, necessary=False),
        AlertOutcome("newsletter", surfaced=False, intrusive=False, necessary=False),
        AlertOutcome("security", surfaced=True, intrusive=True, necessary=True),
    )
    metric = measure_notification_noise(outcomes)

    assert metric.surfaced_alerts == 2
    assert metric.unnecessary_surfaced_alerts == 1
    assert metric.ratio == 0.5
    assert metric.by_category["newsletter"] == 1.0
    assert metric.by_category["security"] == 0.0


def test_p10_05_fusion_metric_separates_false_and_missed_merges_by_truth_ids() -> None:
    from jarvis_papa.evaluation_core import measure_fusion_accuracy

    metric = measure_fusion_accuracy(
        ground_truth={"a": "s1", "b": "s1", "c": "s2"},
        predicted={"a": "p1", "b": "p2", "c": "p1"},
    )

    assert metric.false_merges == 1
    assert metric.missed_merges == 1
    assert metric.correct_pairs == 1
