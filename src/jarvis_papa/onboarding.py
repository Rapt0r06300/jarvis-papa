from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from jarvis_papa.config import settings
from jarvis_papa.diagnostics import diagnostics


class FirstLaunchDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.marker = settings.runtime_dir / "onboarding-v1.complete"
        self.setWindowTitle("Bienvenue dans Jarvis")
        self.setModal(True)
        self.setMinimumSize(700, 560)
        self.resize(760, 620)
        self._build_ui()
        self._install_style()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 26)
        layout.setSpacing(14)

        title = QLabel(f"Bonjour {settings.user_name}, je suis Jarvis.")
        title.setObjectName("title")
        title.setWordWrap(True)
        layout.addWidget(title)

        intro = QLabel(
            "Je vais vérifier les fonctions principales. Tu n'as rien de technique à configurer ici."
        )
        intro.setObjectName("intro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status = QLabel("Je vérifie que tout est prêt…")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.checks = QVBoxLayout()
        self.checks.setSpacing(8)
        layout.addLayout(self.checks)
        layout.addStretch(1)

        note = QLabel(
            "Une fonction facultative peut être limitée sans empêcher Jarvis de fonctionner. "
            "Tu pourras toujours utiliser le texte si la voix n'est pas disponible."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        retry = QPushButton("Vérifier à nouveau")
        retry.clicked.connect(self.refresh)
        buttons.addWidget(retry)
        buttons.addStretch(1)
        continue_button = QPushButton("Continuer")
        continue_button.setObjectName("primaryButton")
        continue_button.setDefault(True)
        continue_button.clicked.connect(self.accept)
        buttons.addWidget(continue_button)
        layout.addLayout(buttons)

    def _install_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f9fc;
                color: #172338;
                font-family: 'Segoe UI';
                font-size: 16px;
            }
            #title { font-size: 31px; font-weight: 760; color: #172d49; }
            #intro { font-size: 18px; color: #344c66; }
            #status {
                background: #ffffff;
                border: 1px solid #d5e1ed;
                border-radius: 14px;
                padding: 13px;
                font-weight: 650;
            }
            #muted { color: #66758a; }
            QFrame#checkRow {
                background: #ffffff;
                border: 1px solid #d8e2ed;
                border-radius: 13px;
            }
            QLabel#checkLabel { font-size: 17px; font-weight: 680; }
            QLabel#checkOk { color: #12623b; font-weight: 800; }
            QLabel#checkLimited { color: #8a5d05; font-weight: 800; }
            QLabel#checkFailed { color: #9b2d2d; font-weight: 800; }
            QPushButton {
                min-height: 50px;
                padding: 0 20px;
                border-radius: 13px;
                border: 1px solid #c9d6e4;
                background: #ffffff;
                color: #1d3552;
                font-weight: 650;
            }
            QPushButton:focus { border: 2px solid #1769bd; }
            #primaryButton { background: #1769bd; color: white; border-color: #1769bd; }
            """
        )

    def refresh(self) -> None:
        self.status.setText("Je vérifie que tout est prêt…")
        QApplication.processEvents()
        report = diagnostics.run()
        checks = report.get("checks") if isinstance(report.get("checks"), list) else []
        by_id = {
            str(item.get("id")): item
            for item in checks
            if isinstance(item, dict) and item.get("id")
        }
        rows = [
            self._summary_row("Application", "ok", "Jarvis est installé et peut démarrer."),
            self._from_check("Documents", by_id.get("file_search")),
            self._from_check("Internet", by_id.get("browser")),
            self._from_check("IA", by_id.get("local_ai"), optional=True),
            self._from_check("Voix", by_id.get("voice"), optional=True),
            self._from_check("Thunderbird", by_id.get("thunderbird_bridge"), optional=True),
        ]
        self._render(rows)
        failed = sum(item[1] == "error" for item in rows)
        limited = sum(item[1] == "warning" for item in rows)
        if failed:
            self.status.setText(
                "Jarvis peut démarrer, mais une fonction importante a besoin d'une vérification."
            )
        elif limited:
            self.status.setText(
                "Jarvis est prêt. Certaines fonctions facultatives pourront être finalisées plus tard."
            )
        else:
            self.status.setText("Tout est prêt. Tu peux commencer à utiliser Jarvis.")

    @staticmethod
    def _summary_row(label: str, status: str, detail: str) -> tuple[str, str, str]:
        return label, status, detail

    @staticmethod
    def _from_check(
        label: str,
        check: object,
        *,
        optional: bool = False,
    ) -> tuple[str, str, str]:
        if not isinstance(check, dict):
            return label, "warning" if optional else "error", "Vérification non disponible."
        status = str(check.get("status") or "info")
        detail = str(check.get("detail") or "")
        if optional and status in {"error", "warning", "info"}:
            status = "warning"
        elif status == "info":
            status = "ok"
        return label, status, detail

    def _render(self, rows: list[tuple[str, str, str]]) -> None:
        while self.checks.count():
            item = self.checks.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for label, status, detail in rows:
            frame = QFrame()
            frame.setObjectName("checkRow")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(14, 11, 14, 11)
            text_layout = QVBoxLayout()
            name = QLabel(label)
            name.setObjectName("checkLabel")
            text_layout.addWidget(name)
            detail_label = QLabel(self._human_detail(label, status, detail))
            detail_label.setWordWrap(True)
            detail_label.setObjectName("muted")
            text_layout.addWidget(detail_label)
            layout.addLayout(text_layout, 1)
            state = QLabel(
                "✓" if status == "ok" else ("À vérifier" if status == "error" else "Facultatif")
            )
            if status == "ok":
                state.setObjectName("checkOk")
            elif status == "error":
                state.setObjectName("checkFailed")
            else:
                state.setObjectName("checkLimited")
            layout.addWidget(state, alignment=Qt.AlignmentFlag.AlignTop)
            self.checks.addWidget(frame)

    @staticmethod
    def _human_detail(label: str, status: str, detail: str) -> str:
        if status == "ok":
            defaults = {
                "Documents": "Je peux chercher dans les documents autorisés.",
                "Internet": "Je peux consulter le Web quand une information actuelle est nécessaire.",
                "IA": "Le moteur d'aide est disponible.",
                "Voix": "Au moins une voix est disponible.",
                "Thunderbird": "La connexion avec les mails est active.",
            }
            return defaults.get(label, detail or "Prêt.")
        if label == "IA":
            return "Jarvis utilisera son mode de secours si le moteur local n'est pas prêt."
        if label == "Voix":
            return "Jarvis restera entièrement utilisable par écrit."
        if label == "Thunderbird":
            return "Ouvre Thunderbird plus tard pour terminer la connexion avec les mails."
        if label == "Internet":
            return "La consultation du Web pourra être retestée depuis le diagnostic."
        if label == "Documents":
            return "Les dossiers habituels ne sont pas encore accessibles."
        return detail or "Cette fonction pourra être vérifiée plus tard."

    def accept(self) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("completed\n", encoding="utf-8")
        super().accept()


def should_run_onboarding() -> bool:
    if os.environ.get("JARVIS_SKIP_ONBOARDING") == "1":
        return False
    return not (settings.runtime_dir / "onboarding-v1.complete").is_file()


def run_first_launch_onboarding() -> None:
    if not should_run_onboarding():
        return
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Jarvis Papa")
    app.setOrganizationName("Jarvis Papa")
    app.setFont(QFont("Segoe UI", 10))
    dialog = FirstLaunchDialog()
    dialog.exec()


if __name__ == "__main__":
    run_first_launch_onboarding()
