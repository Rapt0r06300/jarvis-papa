from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jarvis_papa import __version__
from jarvis_papa.config import settings
from jarvis_papa.diagnostic_report import export_report
from jarvis_papa.diagnostics import diagnostics
from jarvis_papa.memory import memory_store

_STATUS_TEXT = {
    "ok": ("OK", "Tout fonctionne."),
    "warning": ("DEGRADED", "Jarvis reste utilisable, avec une fonction limitée."),
    "error": ("FAILED", "Cette fonction a besoin d'une vérification."),
    "info": ("OK", "Fonction facultative ou non applicable."),
}


class DiagnosticWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Diagnostic Jarvis")
        self.setMinimumSize(780, 620)
        self.resize(880, 720)
        self._build_ui()
        self._install_style()
        self.refresh()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Diagnostic Jarvis")
        title.setObjectName("title")
        layout.addWidget(title)

        self.summary = QLabel("Je vérifie les fonctions importantes…")
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        self.summary.setAccessibleName("État général de Jarvis")
        layout.addWidget(self.summary)

        explanation = QLabel(
            "Cette page est prévue pour vérifier Jarvis sans terminal ni commandes techniques. "
            "Les fonctions facultatives peuvent être indiquées comme limitées sans empêcher l'utilisation normale."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        layout.addWidget(explanation)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(9)
        scroll.setWidget(self.rows)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        refresh = QPushButton("Vérifier à nouveau")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        export = QPushButton("Exporter le rapport")
        export.setObjectName("primaryButton")
        export.clicked.connect(self.export)
        buttons.addWidget(export)
        buttons.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _install_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f7f9fc;
                color: #172338;
                font-family: 'Segoe UI';
                font-size: 16px;
            }
            #title { font-size: 34px; font-weight: 750; color: #172d49; }
            #summary {
                background: #ffffff;
                border: 1px solid #d5e0eb;
                border-radius: 16px;
                padding: 16px;
                font-size: 19px;
                font-weight: 650;
            }
            #muted { color: #66758a; }
            QFrame#diagnosticRow {
                background: #ffffff;
                border: 1px solid #d8e2ed;
                border-radius: 14px;
            }
            QLabel#rowTitle { font-size: 17px; font-weight: 700; color: #203a58; }
            QLabel#rowDetail { color: #4c6076; }
            QLabel#stateOk { color: #14633c; font-weight: 800; }
            QLabel#stateDegraded { color: #885d08; font-weight: 800; }
            QLabel#stateFailed { color: #9b2d2d; font-weight: 800; }
            QPushButton {
                min-height: 48px;
                padding: 0 18px;
                border-radius: 12px;
                border: 1px solid #c8d6e4;
                background: #ffffff;
                color: #1d3552;
                font-weight: 650;
            }
            QPushButton:hover { background: #eff5fb; }
            QPushButton:focus { border: 2px solid #1769bd; }
            #primaryButton { background: #1769bd; color: white; border-color: #1769bd; }
            """
        )

    def refresh(self) -> None:
        self.summary.setText("Je vérifie Jarvis…")
        QApplication.processEvents()
        report = diagnostics.run()
        checks = report.get("checks") if isinstance(report.get("checks"), list) else []
        memory = memory_store.status()
        checks.append(
            {
                "id": "memory",
                "label": "Mémoire locale",
                "status": "ok" if memory.get("ok") else "error",
                "detail": (
                    f"Mémoire locale prête. {memory.get('active_items', 0)} information(s) durable(s) active(s)."
                ),
                "remediation": "",
            }
        )
        free_gb = shutil.disk_usage(settings.runtime_dir).free / (1024**3)
        checks.append(
            {
                "id": "disk_space",
                "label": "Espace disponible",
                "status": "ok" if free_gb >= 2 else "warning",
                "detail": f"Environ {free_gb:.1f} Go disponibles pour Jarvis et ses fichiers temporaires.",
                "remediation": "Libère un peu d'espace disque si Jarvis manque de place.",
            }
        )
        checks.append(
            {
                "id": "application",
                "label": "Application Jarvis",
                "status": "ok",
                "detail": (
                    f"Jarvis Papa {__version__} est lancé comme application Windows."
                    if getattr(sys, "frozen", False)
                    else f"Jarvis Papa {__version__} est lancé en environnement de développement."
                ),
                "remediation": "",
            }
        )
        self._render_checks(checks)
        errors = sum(str(item.get("status")) == "error" for item in checks if isinstance(item, dict))
        warnings = sum(str(item.get("status")) == "warning" for item in checks if isinstance(item, dict))
        if errors:
            self.summary.setText(
                "Jarvis a besoin d'une vérification sur au moins une fonction. Le reste peut continuer à fonctionner."
            )
        elif warnings:
            self.summary.setText(
                "Jarvis fonctionne, mais certaines fonctions sont momentanément limitées."
            )
        else:
            self.summary.setText("Tout est prêt. Jarvis peut être utilisé normalement.")

    def _render_checks(self, checks: list[object]) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for raw in checks:
            if not isinstance(raw, dict):
                continue
            self.rows_layout.addWidget(self._row(raw))
        self.rows_layout.addStretch(1)

    def _row(self, check: dict[str, object]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("diagnosticRow")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(5)
        top = QHBoxLayout()
        title = QLabel(str(check.get("label") or "Fonction Jarvis"))
        title.setObjectName("rowTitle")
        top.addWidget(title)
        top.addStretch(1)
        raw_status = str(check.get("status") or "info")
        state_text = _STATUS_TEXT.get(raw_status, _STATUS_TEXT["info"])[0]
        state = QLabel(state_text)
        if raw_status == "error":
            state.setObjectName("stateFailed")
        elif raw_status == "warning":
            state.setObjectName("stateDegraded")
        else:
            state.setObjectName("stateOk")
        top.addWidget(state)
        layout.addLayout(top)
        detail = QLabel(str(check.get("detail") or _STATUS_TEXT.get(raw_status, _STATUS_TEXT["info"])[1]))
        detail.setObjectName("rowDetail")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        remediation = str(check.get("remediation") or "").strip()
        if remediation:
            help_label = QLabel(f"À faire : {self._humanize_remediation(remediation)}")
            help_label.setWordWrap(True)
            help_label.setObjectName("rowDetail")
            layout.addWidget(help_label)
        return frame

    @staticmethod
    def _humanize_remediation(text: str) -> str:
        lowered = text.casefold()
        if ".bat" in lowered or "python -m" in lowered or ".ps1" in lowered:
            return "ouvre Jarvis ou relance son installation ; les détails techniques sont masqués ici."
        return text

    def export(self) -> None:
        desktop = Path.home() / "Desktop"
        suggested = (desktop if desktop.is_dir() else Path.home()) / "Rapport-Jarvis.zip"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le rapport Jarvis",
            str(suggested),
            "Rapport ZIP (*.zip)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.casefold() != ".zip":
            destination = destination.with_suffix(".zip")
        try:
            path = export_report(destination)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Diagnostic Jarvis",
                f"Je n'ai pas pu enregistrer le rapport.\n\n{type(exc).__name__}",
            )
            return
        QMessageBox.information(
            self,
            "Diagnostic Jarvis",
            f"Le rapport a été créé ici :\n{path}",
        )


def run() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Diagnostic Jarvis")
    app.setOrganizationName("Jarvis Papa")
    app.setFont(QFont("Segoe UI", 10))
    window = DiagnosticWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    run()
