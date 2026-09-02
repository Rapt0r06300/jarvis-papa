from __future__ import annotations

import time
from threading import Event

import pytest

from jarvis_papa.situations import ProvenanceRef


def _progress():
    from jarvis_papa import runtime_progress

    return runtime_progress


def _evidence() -> ProvenanceRef:
    return ProvenanceRef(
        source="email",
        source_id="message-42",
        observed_at=1_780_000_000.0,
        locator="thunderbird:Inbox",
        content_hash="a" * 64,
    )


def test_p3_01_runtime_events_are_typed_validated_and_evidence_aware() -> None:
    progress = _progress()
    event = progress.RuntimeProgressEvent.create(
        event_type=progress.RuntimeProgressType.DISCOVERY,
        run_id=progress.RunId("run-42"),
        stage_id=progress.StageId("email_triage"),
        timestamp=1_780_000_000.0,
        public_label="Message important détecté",
        evidence=(_evidence(),),
        importance=progress.ProgressImportance.IMPORTANT,
    )
    assert event.run_id.value == "run-42"
    assert event.stage_id.value == "email_triage"
    assert event.timestamp == 1_780_000_000.0
    assert event.evidence[0].source_id == "message-42"
    assert event.to_dict()["event_type"] == "discovery"

    with pytest.raises(ValueError):
        progress.RunId("")
    with pytest.raises(ValueError):
        progress.RuntimeProgressEvent.create(
            event_type=progress.RuntimeProgressType.PROGRESS_UPDATE,
            run_id=progress.RunId("run-42"),
            stage_id=progress.StageId("email_triage"),
            timestamp=1_780_000_001.0,
            progress=1.5,
        )
    with pytest.raises(ValueError):
        progress.RuntimeProgressEvent.create(
            event_type="invented_event",
            run_id=progress.RunId("run-42"),
            stage_id=progress.StageId("email_triage"),
            timestamp=1_780_000_001.0,
        )


def test_p3_02_shared_event_bus_preserves_order_without_slow_consumer_blocking() -> None:
    progress = _progress()
    bus = progress.RuntimeProgressBus()
    ui_events: list[object] = []
    tts_events: list[object] = []
    ui_done = Event()
    tts_done = Event()

    def ui_consumer(event) -> None:
        ui_events.append(event)
        if len(ui_events) == 3:
            ui_done.set()

    def slow_tts_consumer(event) -> None:
        time.sleep(0.08)
        tts_events.append(event)
        if len(tts_events) == 3:
            tts_done.set()

    ui_sub = bus.subscribe("ui", ui_consumer)
    tts_sub = bus.subscribe("tts", slow_tts_consumer)
    events = [
        progress.RuntimeProgressEvent.create(
            event_type=progress.RuntimeProgressType.DISCOVERY,
            run_id=progress.RunId("run-bus"),
            stage_id=progress.StageId("email_triage"),
            timestamp=1_780_000_000.0 + index,
            public_label=f"Découverte {index}",
            evidence=(_evidence(),),
        )
        for index in range(3)
    ]

    started = time.monotonic()
    for event in events:
        bus.publish(event)
    publish_duration = time.monotonic() - started

    assert publish_duration < 0.05
    assert ui_done.wait(1.0)
    assert tts_done.wait(1.0)
    assert ui_events == events
    assert tts_events == events
    ui_sub.close()
    tts_sub.close()
    bus.close()


def test_p3_03_truthful_narration_only_describes_real_event_state() -> None:
    progress = _progress()
    narrator = progress.TruthfulProgressNarrator()
    unrelated = progress.RuntimeProgressEvent.create(
        event_type=progress.RuntimeProgressType.RUN_STARTED,
        run_id=progress.RunId("run-truth"),
        stage_id=progress.StageId("run"),
        timestamp=1_780_000_000.0,
        public_label="Analyse en cours",
    )
    assert "amazon" not in narrator.narrate(unrelated).casefold()

    started = progress.RuntimeProgressEvent.create(
        event_type=progress.RuntimeProgressType.STAGE_STARTED,
        run_id=progress.RunId("run-truth"),
        stage_id=progress.StageId("order_check"),
        timestamp=1_780_000_001.0,
        public_label="Vérification de la commande Amazon",
    )
    assert "amazon" in narrator.narrate(started).casefold()

    failed = progress.RuntimeProgressEvent.create(
        event_type=progress.RuntimeProgressType.STAGE_COMPLETED,
        run_id=progress.RunId("run-truth"),
        stage_id=progress.StageId("order_check"),
        timestamp=1_780_000_002.0,
        public_label="Vérification de la commande Amazon",
        outcome=progress.StageOutcome.FAILED,
    )
    failed_text = narrator.narrate(failed).casefold()
    assert "terminée avec succès" not in failed_text
    assert "échec" in failed_text or "interromp" in failed_text


def test_p3_04_workflow_adapters_emit_human_stages_not_tool_call_noise() -> None:
    progress = _progress()
    adapter = progress.WorkflowProgressAdapter()
    expected = {
        "email_triage": "Analyse des nouveaux messages",
        "situation_correlation": "Regroupement des informations liées",
        "order_parcel_check": "Vérification des commandes et colis",
        "marketplace_analysis": "Analyse des échanges de vente",
        "document_search": "Recherche des documents utiles",
    }
    for workflow, label in expected.items():
        event = adapter.stage_started(
            workflow,
            run_id=progress.RunId("run-stage"),
            timestamp=1_780_000_000.0,
        )
        assert event.event_type is progress.RuntimeProgressType.STAGE_STARTED
        assert event.public_label == label
        assert "tool" not in event.public_label.casefold()
        assert "imap" not in event.public_label.casefold()
        assert "http" not in event.public_label.casefold()

    with pytest.raises(KeyError):
        adapter.stage_started(
            "imap.listMessages",
            run_id=progress.RunId("run-stage"),
            timestamp=1_780_000_000.0,
        )


def test_p3_05_progress_throttle_bounds_noise_but_critical_discovery_bypasses() -> None:
    progress = _progress()
    throttle = progress.ProgressThrottle(min_interval_seconds=2.0)
    surfaced = 0
    for index in range(100):
        event = progress.RuntimeProgressEvent.create(
            event_type=progress.RuntimeProgressType.PROGRESS_UPDATE,
            run_id=progress.RunId("run-throttle"),
            stage_id=progress.StageId("email_triage"),
            timestamp=1_780_000_000.0 + (index * 0.01),
            public_label="Analyse des nouveaux messages",
            progress=index / 100,
        )
        surfaced += int(throttle.should_surface(event))
    assert surfaced <= 2

    critical = progress.RuntimeProgressEvent.create(
        event_type=progress.RuntimeProgressType.DISCOVERY,
        run_id=progress.RunId("run-throttle"),
        stage_id=progress.StageId("email_triage"),
        timestamp=1_780_000_000.5,
        public_label="Alerte de sécurité bancaire",
        evidence=(_evidence(),),
        importance=progress.ProgressImportance.CRITICAL,
    )
    assert throttle.should_surface(critical) is True


def test_p3_06_burst_coalescing_is_deterministic_and_never_hides_critical_discovery() -> None:
    progress = _progress()
    normal_events = tuple(
        progress.RuntimeProgressEvent.create(
            event_type=progress.RuntimeProgressType.PROGRESS_UPDATE,
            run_id=progress.RunId("run-coalesce"),
            stage_id=progress.StageId("email_triage"),
            timestamp=1_780_000_000.0 + (index * 0.1),
            public_label="Analyse des nouveaux messages",
            progress=(index + 1) / 10,
        )
        for index in range(5)
    )
    first = progress.coalesce_progress_events(normal_events, window_seconds=1.0)
    second = progress.coalesce_progress_events(normal_events, window_seconds=1.0)
    assert first == second
    assert len(first) == 1
    assert first[0].event_count == 5
    assert len(first[0].text) < 240

    critical = progress.RuntimeProgressEvent.create(
        event_type=progress.RuntimeProgressType.DISCOVERY,
        run_id=progress.RunId("run-coalesce"),
        stage_id=progress.StageId("email_triage"),
        timestamp=1_780_000_000.25,
        public_label="Fraude bancaire potentielle à vérifier",
        evidence=(_evidence(),),
        importance=progress.ProgressImportance.CRITICAL,
    )
    merged = progress.coalesce_progress_events(normal_events[:2] + (critical,) + normal_events[2:], window_seconds=1.0)
    assert len(merged) == 1
    assert "fraude bancaire" in merged[0].text.casefold()
    assert merged[0].importance is progress.ProgressImportance.CRITICAL
