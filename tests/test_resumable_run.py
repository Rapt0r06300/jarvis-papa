from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import NormalizedEvent, ProvenanceRef


def _run_control():
    from jarvis_papa import run_control

    return run_control


def _event(index: int) -> NormalizedEvent:
    observed = 1_780_000_000.0 + index
    provenance = ProvenanceRef(
        source="synthetic",
        source_id=f"event-{index}",
        observed_at=observed,
        locator="fixture:p3b",
        content_hash=f"{index:064x}"[-64:],
    )
    return NormalizedEvent(
        source="synthetic",
        source_event_id=f"event-{index}",
        event_type="synthetic_progress",
        occurred_at=observed,
        observed_at=observed,
        payload_summary=f"Synthetic event {index}",
        provenance=(provenance,),
        confidence=1.0,
        source_version="p3b-v1",
    )


def test_p3_07_desktop_acknowledges_before_starting_background_worker() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "jarvis_papa" / "professional_desktop.py"
    ).read_text(encoding="utf-8")
    start = source.index("    def send_chat(self) -> None:")
    end = source.index("    def _chat_result", start)
    block = source[start:end]

    acknowledgement = block.index("self.chat_state.setText(\"Jarvis réfléchit…\")")
    activity = block.index("self.begin_activity(")
    background = block.index("self._worker(")

    assert acknowledgement < activity < background
    assert "self.setEnabled(False)" not in block
    assert "worker = ApiWorker(function)" in source
    assert "self.pool.start(worker)" in source


@pytest.mark.skipif(sys.platform != "win32", reason="PySide6 desktop E2E targets Windows")
def test_p3_07_long_synthetic_worker_keeps_qt_event_loop_responsive() -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from jarvis_papa.professional_desktop import ProfessionalMainWindow

    app = QApplication.instance() or QApplication([])
    window = ProfessionalMainWindow()
    heartbeat = {"seen": False}
    finished = {"seen": False}

    window.begin_activity("Test long en arrière-plan", speak=False)
    QTimer.singleShot(20, lambda: heartbeat.__setitem__("seen", True))
    window._worker(
        lambda: (time.sleep(0.25), {"ok": True})[1],
        lambda _result: finished.__setitem__("seen", True),
    )

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and not finished["seen"]:
        app.processEvents()
        time.sleep(0.005)

    assert heartbeat["seen"] is True
    assert finished["seen"] is True
    window.close()


def test_p3_08_worker_failure_is_structured_and_existing_desktop_worker_is_backgrounded(
    tmp_path,
) -> None:
    control = _run_control()
    source = (
        Path(__file__).parents[1] / "src" / "jarvis_papa" / "professional_desktop.py"
    ).read_text(encoding="utf-8")
    assert "worker = ApiWorker(function)" in source
    assert "self.pool.start(worker)" in source

    store = SituationStore(tmp_path / "situations.sqlite3")
    runner = control.ResumableEventRun(store)

    def fail(_event: NormalizedEvent) -> None:
        raise RuntimeError("synthetic source failure")

    result = runner.execute(
        (_event(1),),
        fail,
        run_id="run-p3b-failure",
    )
    assert result.state is control.RunState.FAILED
    assert isinstance(result.failure, control.RunFailure)
    assert result.failure.exception_type == "RuntimeError"
    assert result.failure.event_identity
    assert "synthetic source failure" in result.failure.message


def test_p3_09_cancel_at_event_250_preserves_completed_work_and_resumes_safely(tmp_path) -> None:
    control = _run_control()
    store = SituationStore(tmp_path / "situations.sqlite3")
    runner = control.ResumableEventRun(store)
    token = control.CancellationToken()
    events = tuple(_event(index) for index in range(500))
    first_seen: list[str] = []

    def first_pass(event: NormalizedEvent) -> None:
        first_seen.append(event.identity_key)
        if len(first_seen) == 250:
            token.cancel("Robert a demandé Stop")

    first = runner.execute(
        events,
        first_pass,
        run_id="run-p3b-cancel",
        cancellation=token,
    )
    assert first.state is control.RunState.CANCELLED
    assert first.processed_count == 250
    assert len(set(first_seen)) == 250
    checkpoint = store.get_checkpoint("runtime-run:run-p3b-cancel", lane="live")
    assert checkpoint is not None
    assert checkpoint["cursor"] == events[249].identity_key
    assert all(store.event_processed(event.identity_key) for event in events[:250])

    resumed_seen: list[str] = []
    second = control.ResumableEventRun(store).execute(
        events,
        lambda event: resumed_seen.append(event.identity_key),
        run_id="run-p3b-cancel",
        cancellation=control.CancellationToken(),
    )
    assert second.state is control.RunState.COMPLETED
    assert second.processed_count == 250
    assert second.skipped_completed == 250
    assert set(first_seen).isdisjoint(resumed_seen)
    assert len(resumed_seen) == 250
    assert all(store.event_processed(event.identity_key) for event in events)


def test_p3_10_crash_restart_skips_completed_and_replays_only_incomplete_event(tmp_path) -> None:
    control = _run_control()
    store = SituationStore(tmp_path / "situations.sqlite3")
    events = tuple(_event(index) for index in range(6))
    first_seen: list[str] = []

    def crash_on_third(event: NormalizedEvent) -> None:
        first_seen.append(event.identity_key)
        if event.identity_key == events[2].identity_key:
            raise RuntimeError("simulated crash boundary")

    first = control.ResumableEventRun(store).execute(
        events,
        crash_on_third,
        run_id="run-p3b-restart",
    )
    assert first.state is control.RunState.FAILED
    assert store.event_processed(events[0].identity_key)
    assert store.event_processed(events[1].identity_key)
    assert not store.event_processed(events[2].identity_key)

    resumed_seen: list[str] = []
    second = control.ResumableEventRun(store).execute(
        events,
        lambda event: resumed_seen.append(event.identity_key),
        run_id="run-p3b-restart",
    )
    assert second.state is control.RunState.COMPLETED
    assert second.skipped_completed == 2
    assert resumed_seen[0] == events[2].identity_key
    assert events[0].identity_key not in resumed_seen
    assert events[1].identity_key not in resumed_seen
    assert len(resumed_seen) == 4
    assert all(store.event_processed(event.identity_key) for event in events)
