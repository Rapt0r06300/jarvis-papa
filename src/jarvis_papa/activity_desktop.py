from __future__ import annotations

import sys
import time
from functools import partial

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from jarvis_papa.activity_surface import DailyActivityHistory, RuntimeActivitySurface, StartupTiming
from jarvis_papa.config import settings
from jarvis_papa.metrics import local_metrics
from jarvis_papa.professional_desktop import BackendService
from jarvis_papa.professional_desktop_plus import JarvisProfessionalWindow
from jarvis_papa.runtime_progress import (
    ProgressImportance,
    RunId,
    RuntimeProgressEvent,
    RuntimeProgressType,
    StageId,
    StageOutcome,
)
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.system_reliability import backup_manager, session_recovery

_PROCESS_STARTED_AT = time.monotonic()


class JarvisActivityWindow(JarvisProfessionalWindow):
    """Canonical professional desktop with evidence-backed human activity surfaces."""

    def __init__(self) -> None:
        self.runtime_activity = RuntimeActivitySurface()
        self.startup_timing = StartupTiming(
            local_metrics,
            process_started_at=_PROCESS_STARTED_AT,
        )
        self._startup_analysis_started = False
        self._startup_background_completed = False
        self._activity_run_id = RunId(f"desktop-{int(time.time() * 1000)}")
        self._silent_activity_serials: set[int] = set()
        super().__init__()
        self._install_runtime_activity_surface()
        self.startup_timing.mark_ui_ready()
        self.daily_activity_timer = QTimer(self)
        self.daily_activity_timer.setInterval(30_000)
        self.daily_activity_timer.timeout.connect(self.refresh_daily_activity)
        self.daily_activity_timer.start()
        QTimer.singleShot(900, self.refresh_daily_activity)

    def _install_runtime_activity_surface(self) -> None:
        frame = self.activity_title.parentWidget()
        layout = frame.layout() if frame is not None else None
        self.runtime_activity_heading = QLabel("Ce que Jarvis fait")
        self.runtime_activity_heading.setObjectName("activityHeading")
        self.runtime_activity_heading.setAccessibleName("Ce que Jarvis fait maintenant")
        if layout is not None:
            layout.insertWidget(0, self.runtime_activity_heading)

        self.daily_activity_heading = QLabel("Ce que Jarvis a fait aujourd’hui")
        self.daily_activity_heading.setObjectName("dailyActivityHeading")
        self.daily_activity_label = QLabel("Je prépare l’historique vérifiable de la journée.")
        self.daily_activity_label.setObjectName("dailyActivityDetail")
        self.daily_activity_label.setWordWrap(True)
        self.daily_activity_label.setAccessibleName("Activité vérifiée de Jarvis aujourd'hui")
        if layout is not None:
            layout.addWidget(self.daily_activity_heading)
            layout.addWidget(self.daily_activity_label)

    def consume_runtime_progress(self, event: RuntimeProgressEvent) -> None:
        snapshot = self.runtime_activity.consume(event)
        self.startup_timing.observe_runtime_event(event)
        self.activity_title.setText(snapshot.current_stage)
        self.activity_detail.setText(snapshot.current_detail)
        counters: list[str] = []
        if snapshot.discovery_count:
            counters.append(f"{snapshot.discovery_count} découverte(s)")
        if snapshot.pending_decision_count:
            counters.append(f"{snapshot.pending_decision_count} décision(s) en attente")
        lines = list(snapshot.recent_activity[-4:])
        if counters:
            lines.append(" · ".join(counters))
        self.activity_log.setText("\n".join(lines))
        self.activity_log.setVisible(bool(lines))
        self.left_state.setText(snapshot.current_detail)

    def begin_activity(
        self,
        text: str,
        *,
        wait_text: str | None = None,
        speak: bool = True,
    ) -> int:
        self.activity_serial += 1
        serial = self.activity_serial
        if not speak:
            self._silent_activity_serials.add(serial)
        self.busy = True
        self.activity_started_at = time.monotonic()
        self.activity_progress.show()
        self.status.setText("●  Jarvis travaille…")
        self._history_add(text)
        if speak:
            self._say(text)
        self.caption.setText(text)
        self.left_state.setText(text)
        event = RuntimeProgressEvent.create(
            event_type=RuntimeProgressType.STAGE_STARTED,
            run_id=self._activity_run_id,
            stage_id=StageId(f"desktop_activity_{serial}"),
            timestamp=time.time(),
            public_label=text,
        )
        self.consume_runtime_progress(event)
        if wait_text:
            QTimer.singleShot(3200, partial(self._maybe_wait_update, serial, wait_text))
        return serial

    def _maybe_wait_update(self, serial: int, text: str) -> None:
        if serial not in self._silent_activity_serials:
            super()._maybe_wait_update(serial, text)
            return
        if not self.busy or serial != self.activity_serial:
            return
        self.activity_detail.setText(text)
        self._history_add(text)
        self.caption.setText(text)
        self.left_state.setText(text)

    def finish_activity(self, text: str, *, success: bool = True, speak: bool = True) -> None:
        serial = self.activity_serial
        super().finish_activity(text, success=success, speak=speak)
        event = RuntimeProgressEvent.create(
            event_type=RuntimeProgressType.STAGE_COMPLETED,
            run_id=self._activity_run_id,
            stage_id=StageId(f"desktop_activity_{max(1, serial)}"),
            timestamp=time.time(),
            public_label=text,
            outcome=StageOutcome.COMPLETED if success else StageOutcome.FAILED,
            importance=(
                ProgressImportance.NORMAL if success else ProgressImportance.IMPORTANT
            ),
        )
        self.consume_runtime_progress(event)
        self._silent_activity_serials.discard(serial)

    def finish_partial(self, text: str, *, speak: bool = True) -> None:
        serial = self.activity_serial
        super().finish_partial(text, speak=speak)
        event = RuntimeProgressEvent.create(
            event_type=RuntimeProgressType.APPROVAL_REQUIRED,
            run_id=self._activity_run_id,
            stage_id=StageId(f"desktop_activity_{max(1, serial)}"),
            timestamp=time.time(),
            public_label=text,
            importance=ProgressImportance.IMPORTANT,
        )
        self.consume_runtime_progress(event)
        self._silent_activity_serials.discard(serial)

    def refresh(self) -> None:
        if not self._startup_analysis_started:
            self._startup_analysis_started = True
            self.startup_timing.mark_analysis_started()
        super().refresh()

    def _receive_cards(self, cards: list[dict[str, object]]) -> None:
        super()._receive_cards(cards)
        if cards:
            event = RuntimeProgressEvent.create(
                event_type=RuntimeProgressType.PROPOSAL_READY,
                run_id=self._activity_run_id,
                stage_id=StageId("startup_attention"),
                timestamp=time.time(),
                public_label=(
                    f"{min(len(cards), 3)} chose(s) méritent ton attention"
                ),
                importance=ProgressImportance.IMPORTANT,
            )
        else:
            event = RuntimeProgressEvent.create(
                event_type=RuntimeProgressType.RUN_COMPLETED,
                run_id=self._activity_run_id,
                stage_id=StageId("startup_attention"),
                timestamp=time.time(),
                public_label="Aucune priorité détectée pour le moment",
            )
        self.consume_runtime_progress(event)
        if not self._startup_background_completed:
            self._startup_background_completed = True
            self.startup_timing.mark_background_analysis_completed()

    def refresh_daily_activity(self) -> None:
        self._worker(
            lambda: DailyActivityHistory(SituationStore()).today().to_dict(),
            self._apply_daily_activity,
            on_error=lambda _message: None,
        )

    def _apply_daily_activity(self, payload: dict[str, object]) -> None:
        count = int(payload.get("observed_count") or 0)
        source_counts = (
            payload.get("source_counts")
            if isinstance(payload.get("source_counts"), dict)
            else {}
        )
        entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
        if not count:
            self.daily_activity_label.setText(
                "Aucune nouvelle activité persistée n’est encore disponible aujourd’hui."
            )
            return
        sources = ", ".join(
            f"{source} : {int(value)}"
            for source, value in sorted(source_counts.items())
            if isinstance(value, (int, float))
        )
        summaries = [
            str(item.get("summary") or "")
            for item in entries[-3:]
            if isinstance(item, dict) and item.get("summary")
        ]
        detail = f"{count} information(s) traitée(s)"
        if sources:
            detail += f" · {sources}"
        if summaries:
            detail += "\n" + " · ".join(summaries)
        self.daily_activity_label.setText(detail)


def run() -> None:
    """Start the canonical Windows desktop with runtime activity instrumentation."""

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setOrganizationName("Jarvis Papa")
    app.setFont(QFont("Segoe UI", 10))

    lock = QLockFile(str((settings.runtime_dir / "jarvis-desktop.lock").resolve()))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Jarvis", "Jarvis est déjà ouvert sur cet ordinateur.")
        return

    recovery = session_recovery.begin()
    recovery_backup = None
    if bool(recovery.get("previous_unclean")):
        recovery_backup = backup_manager.create("crash-recovery")

    backend = BackendService()
    if not backend.start():
        session_recovery.end()
        QMessageBox.critical(
            None,
            "Jarvis",
            "Jarvis n'a pas pu démarrer son service local. Redémarre l'application ou lance le diagnostic.",
        )
        lock.unlock()
        return

    exit_code = 1
    try:
        window = JarvisActivityWindow()
        window.show()
        if bool(recovery.get("previous_unclean")):
            detail = "Le dernier arrêt de Jarvis n'était pas propre."
            if recovery_backup is not None and recovery_backup.ok:
                detail += " Une sauvegarde de sécurité a été créée avant de reprendre."
            QTimer.singleShot(
                400,
                lambda: QMessageBox.information(window, "Récupération Jarvis", detail),
            )
        exit_code = app.exec()
    finally:
        backend.stop()
        session_recovery.end()
        lock.unlock()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    run()
