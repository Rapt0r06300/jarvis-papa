from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis_papa.metrics import LocalMetrics
from jarvis_papa.runtime_progress import (
    ProgressImportance,
    RunId,
    RuntimeProgressEvent,
    RuntimeProgressType,
    StageId,
)
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import NormalizedEvent, Situation, SituationDomain


def _event(
    event_type: RuntimeProgressType,
    label: str,
    *,
    at: float,
    stage: str = "email_triage",
    importance: ProgressImportance = ProgressImportance.NORMAL,
) -> RuntimeProgressEvent:
    return RuntimeProgressEvent.create(
        event_type=event_type,
        run_id=RunId("run-p3e"),
        stage_id=StageId(stage),
        timestamp=at,
        public_label=label,
        importance=importance,
    )


def test_p3_18_activity_surface_consumes_mail_and_parcel_runtime_events() -> None:
    from jarvis_papa.activity_surface import RuntimeActivitySurface

    surface = RuntimeActivitySurface()
    surface.consume(
        _event(
            RuntimeProgressType.STAGE_STARTED,
            "Analyse des nouveaux messages",
            at=100.0,
            stage="email_triage",
        )
    )
    surface.consume(
        _event(
            RuntimeProgressType.STAGE_STARTED,
            "Vérification des commandes et colis",
            at=101.0,
            stage="order_parcel_check",
        )
    )
    surface.consume(
        _event(
            RuntimeProgressType.DISCOVERY,
            "Un colis est disponible au point relais",
            at=102.0,
            stage="order_parcel_check",
            importance=ProgressImportance.IMPORTANT,
        )
    )
    surface.consume(
        _event(
            RuntimeProgressType.APPROVAL_REQUIRED,
            "Décider si le colis doit être retiré aujourd'hui",
            at=103.0,
            stage="order_parcel_check",
            importance=ProgressImportance.IMPORTANT,
        )
    )

    snapshot = surface.snapshot()
    assert snapshot.current_stage == "Vérification des commandes et colis"
    assert snapshot.discovery_count == 1
    assert snapshot.pending_decision_count == 1
    assert any("Analyse des nouveaux messages" in line for line in snapshot.recent_activity)
    assert any("colis" in line.casefold() for line in snapshot.recent_activity)


def test_p3_18_activity_surface_hides_technical_labels() -> None:
    from jarvis_papa.activity_surface import RuntimeActivitySurface

    surface = RuntimeActivitySurface()
    snapshot = surface.consume(
        _event(
            RuntimeProgressType.STAGE_STARTED,
            'tool=mail.search model=qwen3 route=fast {"secret":"value"}',
            at=110.0,
        )
    )

    rendered = " ".join((snapshot.current_stage, snapshot.current_detail, *snapshot.recent_activity))
    lowered = rendered.casefold()
    assert "tool=" not in lowered
    assert "model=" not in lowered
    assert "route=" not in lowered
    assert "{\"" not in rendered
    assert "nouvelle étape" in lowered


def _activity_store(tmp_path: Path) -> tuple[SituationStore, tuple[str, str]]:
    store = SituationStore(tmp_path / "activity.sqlite3")
    situation = Situation.create(
        "Journée de Robert",
        domain=SituationDomain.GENERIC,
        state="active",
        confidence=0.9,
    )
    mail = NormalizedEvent(
        source="mail",
        source_event_id="mail-1",
        event_type="important_mail",
        occurred_at=1_788_393_700.0,
        observed_at=1_788_393_710.0,
        payload_summary="Un message important a été trié.",
        confidence=0.95,
    )
    parcel = NormalizedEvent(
        source="amazon",
        source_event_id="parcel-1",
        event_type="pickup_ready",
        occurred_at=1_788_393_800.0,
        observed_at=1_788_393_810.0,
        payload_summary="Un colis disponible a été détecté.",
        confidence=0.99,
    )
    old = NormalizedEvent(
        source="mail",
        source_event_id="old-mail",
        event_type="old_information",
        occurred_at=1_788_300_000.0,
        observed_at=1_788_300_010.0,
        payload_summary="Ancienne information hors journée.",
        confidence=0.9,
    )
    for event in (mail, parcel, old):
        store.ingest_event(event)
        store.mark_event_processed(event.identity_key)
        situation.add_event(event)
    store.save_situation(situation, correlation_keys=("activity:today",))
    return store, (mail.identity_key, parcel.identity_key)


def test_p3_19_daily_activity_matches_persisted_event_ledger(tmp_path: Path) -> None:
    from jarvis_papa.activity_surface import DailyActivityHistory

    store, expected_keys = _activity_store(tmp_path)
    history = DailyActivityHistory(store).between(
        start_at=1_788_393_600.0,
        end_at=1_788_480_000.0,
    )

    assert history.observed_count == 2
    assert history.source_counts == {"amazon": 1, "mail": 1}
    assert tuple(entry.evidence_id for entry in history.entries) == expected_keys
    assert all(entry.evidence_kind == "event" for entry in history.entries)
    payload = history.to_dict()
    assert "time_saved" not in json.dumps(payload).casefold()
    assert "minutes_saved" not in json.dumps(payload).casefold()


def test_p3_20_startup_metrics_are_content_free_and_baseline_comparable(tmp_path: Path) -> None:
    from jarvis_papa.activity_surface import StartupBaseline, StartupTiming

    metrics = LocalMetrics(tmp_path / "metrics.jsonl")
    tracker = StartupTiming(metrics, process_started_at=10.0)
    tracker.mark_ui_ready(at=10.20)
    tracker.mark_analysis_started(at=10.25)
    tracker.observe_runtime_event(
        _event(
            RuntimeProgressType.DISCOVERY,
            "SECRET-MAIL-CONTENT should never be persisted",
            at=1_788_393_900.0,
            importance=ProgressImportance.IMPORTANT,
        ),
        at=10.70,
    )
    tracker.mark_background_analysis_completed(at=11.50)

    snapshot = tracker.snapshot()
    assert snapshot.ui_ready_ms == pytest.approx(200.0)
    assert snapshot.analysis_started_ms == pytest.approx(250.0)
    assert snapshot.first_useful_information_ms == pytest.approx(700.0)
    assert snapshot.background_analysis_completed_ms == pytest.approx(1500.0)
    assert snapshot.ui_ready_ms < snapshot.background_analysis_completed_ms

    raw = (tmp_path / "metrics.jsonl").read_text(encoding="utf-8")
    assert "SECRET-MAIL-CONTENT" not in raw
    assert "startup.ui_ready" in raw
    assert "startup.first_useful_information" in raw

    baseline = StartupBaseline(ui_ready_ms=250.0, first_useful_information_ms=800.0)
    comparison = baseline.compare(snapshot, allowed_regression_ratio=1.10)
    assert comparison.passed is True
    strict = StartupBaseline(ui_ready_ms=100.0, first_useful_information_ms=300.0)
    assert strict.compare(snapshot, allowed_regression_ratio=1.05).passed is False


@pytest.mark.skipif(sys.platform != "win32", reason="canonical desktop requires Windows PySide6")
def test_p3_18_canonical_desktop_exposes_runtime_activity_surface() -> None:
    script = r'''
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication
from jarvis_papa.activity_desktop import JarvisActivityWindow
from jarvis_papa.professional_desktop_plus import JarvisProfessionalWindow
from jarvis_papa.runtime_progress import RunId, RuntimeProgressEvent, RuntimeProgressType, StageId

JarvisActivityWindow._say = lambda *_args, **_kwargs: None
JarvisActivityWindow.refresh = lambda _self: None
JarvisActivityWindow.refresh_diagnostics = lambda _self: None
JarvisActivityWindow.refresh_capabilities = lambda _self: None
JarvisActivityWindow.refresh_daily_activity = lambda _self: None
JarvisActivityWindow._install_overlay = lambda _self: None
JarvisActivityWindow._install_notifications = lambda _self: None

app = QApplication.instance() or QApplication([])
window = JarvisActivityWindow()
assert issubclass(JarvisActivityWindow, JarvisProfessionalWindow)
assert window.runtime_activity_heading.text() == "Ce que Jarvis fait"
event = RuntimeProgressEvent.create(
    event_type=RuntimeProgressType.STAGE_STARTED,
    run_id=RunId("run-p3e-subprocess"),
    stage_id=StageId("email_triage"),
    timestamp=120.0,
    public_label="Analyse des nouveaux messages",
)
window.consume_runtime_progress(event)
assert "Analyse des nouveaux messages" in window.activity_detail.text()
window.begin_activity("Je vérifie une sauvegarde locale.", speak=False)
for timer_name in (
    "speaking_timer",
    "activity_timer",
    "refresh_timer",
    "voice_timer",
    "daily_activity_timer",
):
    timer = getattr(window, timer_name, None)
    if timer is not None:
        timer.stop()
window.close()
window.deleteLater()
QThreadPool.globalInstance().waitForDone(1000)
app.processEvents()
app.quit()
'''
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
