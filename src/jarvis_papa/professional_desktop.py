from __future__ import annotations

import sys
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from jarvis_papa.config import settings
from jarvis_papa.desktop_app import ApiClient, ApiWorker, AvatarWidget, BackendService, FileChoiceDialog


class ProfessionalMainWindow(QMainWindow):
    """Proactive, transparent and simple supervision surface for Jarvis."""

    def __init__(self) -> None:
        super().__init__()
        self.api = ApiClient()
        self.pool = QThreadPool.globalInstance()
        self.last_voice_event = 0
        self.latest_cards: list[dict[str, object]] = []
        self.selected_card_ids: set[str] = set()
        self.proposal_checks: dict[str, QCheckBox] = {}
        self.newsletter_count = 0
        self.intro_announced = False
        self.activity_serial = 0
        self.activity_started_at: float | None = None
        self.activity_history: list[str] = []
        self.busy = False

        self.speaking_timer = QTimer(self)
        self.speaking_timer.setSingleShot(True)
        self.speaking_timer.timeout.connect(self._stop_speaking)

        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self._update_activity_elapsed)
        self.activity_timer.start(1000)

        self.setWindowTitle("Jarvis · Assistant personnel")
        self.setMinimumSize(1080, 720)
        self.resize(1240, 820)
        self._build_ui()
        self._install_style()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(5000)
        self.voice_timer = QTimer(self)
        self.voice_timer.timeout.connect(self.poll_voice)
        self.voice_timer.start(650)

        QTimer.singleShot(150, self.refresh)
        QTimer.singleShot(350, self.refresh_diagnostics)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        assistant_panel = QFrame()
        assistant_panel.setObjectName("assistantPanel")
        assistant_panel.setMinimumWidth(320)
        assistant_panel.setMaximumWidth(395)
        assistant_layout = QVBoxLayout(assistant_panel)
        assistant_layout.setContentsMargins(24, 24, 24, 26)
        assistant_layout.addStretch(1)

        self.avatar = AvatarWidget()
        assistant_layout.addWidget(self.avatar, 5)

        self.caption = QLabel("Je démarre et je regarde ce qui mérite ton attention.")
        self.caption.setWordWrap(True)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setObjectName("caption")
        assistant_layout.addWidget(self.caption)

        self.left_state = QLabel("Jarvis analyse la situation…")
        self.left_state.setWordWrap(True)
        self.left_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_state.setObjectName("assistantState")
        assistant_layout.addWidget(self.left_state)
        assistant_layout.addStretch(1)
        main.addWidget(assistant_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(34, 28, 34, 26)
        content_layout.setSpacing(14)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        self.hello = QLabel(f"Bonjour {settings.user_name}")
        self.hello.setObjectName("hello")
        subtitle = QLabel("Je prépare les options utiles. Tu gardes toujours le dernier mot.")
        subtitle.setObjectName("muted")
        identity.addWidget(self.hello)
        identity.addWidget(subtitle)
        header.addLayout(identity)
        header.addStretch(1)
        self.status = QLabel("●  Démarrage…")
        self.status.setObjectName("status")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignTop)
        content_layout.addLayout(header)

        proposal_frame = QFrame()
        proposal_frame.setObjectName("proposalPanel")
        proposal_layout = QVBoxLayout(proposal_frame)
        proposal_layout.setContentsMargins(20, 18, 20, 18)
        proposal_layout.setSpacing(10)

        proposal_head = QHBoxLayout()
        proposal_titles = QVBoxLayout()
        self.proposal_title = QLabel("On commence par quoi ?")
        self.proposal_title.setObjectName("proposalTitle")
        self.proposal_intro = QLabel(
            "J’ai préparé quelques options. Tu peux en choisir une ou plusieurs."
        )
        self.proposal_intro.setObjectName("muted")
        self.proposal_intro.setWordWrap(True)
        proposal_titles.addWidget(self.proposal_title)
        proposal_titles.addWidget(self.proposal_intro)
        proposal_head.addLayout(proposal_titles)
        proposal_head.addStretch(1)
        self.start_selection_button = QPushButton("Commencer ma sélection")
        self.start_selection_button.setObjectName("primaryButton")
        self.start_selection_button.clicked.connect(self.start_selected_proposals)
        proposal_head.addWidget(self.start_selection_button)
        proposal_layout.addLayout(proposal_head)

        self.proposals_container = QWidget()
        self.proposals_layout = QHBoxLayout(self.proposals_container)
        self.proposals_layout.setContentsMargins(0, 4, 0, 0)
        self.proposals_layout.setSpacing(10)
        proposal_layout.addWidget(self.proposals_container)
        content_layout.addWidget(proposal_frame)

        activity_frame = QFrame()
        activity_frame.setObjectName("activityPanel")
        activity_layout = QVBoxLayout(activity_frame)
        activity_layout.setContentsMargins(18, 14, 18, 14)
        activity_layout.setSpacing(7)

        activity_head = QHBoxLayout()
        self.activity_title = QLabel("Je suis prêt")
        self.activity_title.setObjectName("activityTitle")
        self.activity_elapsed = QLabel("")
        self.activity_elapsed.setObjectName("muted")
        activity_head.addWidget(self.activity_title)
        activity_head.addStretch(1)
        activity_head.addWidget(self.activity_elapsed)
        activity_layout.addLayout(activity_head)

        self.activity_detail = QLabel("Dès que tu choisis quelque chose, je te montre chaque étape ici.")
        self.activity_detail.setWordWrap(True)
        self.activity_detail.setObjectName("activityDetail")
        activity_layout.addWidget(self.activity_detail)

        self.activity_progress = QProgressBar()
        self.activity_progress.setRange(0, 0)
        self.activity_progress.setTextVisible(False)
        self.activity_progress.setFixedHeight(8)
        self.activity_progress.hide()
        activity_layout.addWidget(self.activity_progress)

        self.activity_log = QLabel("")
        self.activity_log.setWordWrap(True)
        self.activity_log.setObjectName("activityLog")
        self.activity_log.hide()
        activity_layout.addWidget(self.activity_log)
        content_layout.addWidget(activity_frame)

        section_head = QHBoxLayout()
        self.section = QLabel("Détails et choix")
        self.section.setObjectName("sectionTitle")
        section_head.addWidget(self.section)
        section_head.addStretch(1)
        self.show_all_button = QPushButton("Tout afficher")
        self.show_all_button.setObjectName("linkButton")
        self.show_all_button.clicked.connect(self.show_all_cards)
        self.show_all_button.hide()
        section_head.addWidget(self.show_all_button)
        content_layout.addLayout(section_head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch(1)
        scroll.setWidget(self.cards_container)
        content_layout.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self.newsletter_label = QLabel("0 newsletter à ranger")
        self.newsletter_label.setObjectName("muted")
        bottom.addWidget(self.newsletter_label)
        bottom.addStretch(1)
        sort_button = QPushButton("Ranger les newsletters")
        sort_button.setObjectName("linkButton")
        sort_button.clicked.connect(self.sort_newsletters)
        bottom.addWidget(sort_button)
        content_layout.addLayout(bottom)

        main.addWidget(content, 1)

    def _install_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f7f9fc;
                color: #172338;
                font-family: 'Segoe UI';
                font-size: 16px;
            }
            #assistantPanel {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #e8f3ff, stop:0.55 #f4f8ff, stop:1 #eef2ff);
                border-right: 1px solid #d6e1ef;
            }
            #hello { font-size: 37px; font-weight: 750; color: #15263e; }
            #muted { color: #66758a; }
            #caption {
                background: rgba(255,255,255,0.96);
                border: 1px solid #d1dfef;
                border-radius: 18px;
                padding: 14px;
                color: #29415e;
                font-size: 17px;
                font-weight: 600;
            }
            #assistantState { color: #57708e; padding: 7px; font-size: 14px; }
            #status {
                color: #0f6138;
                background: #ebf8f0;
                border: 1px solid #c8ead5;
                border-radius: 16px;
                padding: 8px 13px;
                font-weight: 700;
            }
            #proposalPanel {
                background: #ffffff;
                border: 1px solid #d6e2ef;
                border-radius: 20px;
            }
            #proposalTitle { font-size: 25px; font-weight: 750; color: #172d49; }
            #proposalCard {
                background: #f7fbff;
                border: 1px solid #d5e5f4;
                border-radius: 16px;
            }
            QCheckBox {
                spacing: 10px;
                font-size: 17px;
                font-weight: 650;
                color: #213a58;
                padding: 12px;
                min-height: 54px;
            }
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                border: 2px solid #8ca9c6;
                border-radius: 7px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #1769bd;
                border-color: #1769bd;
            }
            #activityPanel {
                background: #172d49;
                border: 1px solid #172d49;
                border-radius: 18px;
            }
            #activityTitle { color: #ffffff; font-size: 19px; font-weight: 750; }
            #activityDetail { color: #e2edf8; font-size: 16px; }
            #activityLog { color: #b8cde2; font-size: 13px; }
            QProgressBar { border: none; background: #294968; border-radius: 4px; }
            QProgressBar::chunk { background: #64b5ff; border-radius: 4px; }
            #sectionTitle { font-size: 22px; font-weight: 750; margin-top: 2px; }
            QPushButton {
                min-height: 50px;
                padding: 0 18px;
                border-radius: 13px;
                border: 1px solid #c9d6e4;
                background: #ffffff;
                color: #1d3552;
                font-weight: 650;
            }
            QPushButton:hover { background: #f0f6fc; border-color: #9bb6cf; }
            QPushButton:pressed { background: #e7f0f9; }
            #primaryButton {
                background: #1769bd;
                color: white;
                border-color: #1769bd;
                font-weight: 750;
            }
            #primaryButton:hover { background: #105ba7; }
            #linkButton {
                min-height: 40px;
                border: none;
                background: transparent;
                color: #486784;
                text-decoration: underline;
            }
            QFrame#taskCard {
                background: #ffffff;
                border: 1px solid #d5e0eb;
                border-radius: 18px;
            }
            QLabel#cardTitle { font-size: 20px; font-weight: 750; color: #172d49; }
            QLabel#cardSummary { font-size: 17px; color: #34465d; }
            QLabel#recommendation { color: #1f557d; font-weight: 650; }
            QLabel#deadline {
                color: #7b4b08;
                background: #fff3dd;
                border-radius: 9px;
                padding: 5px 8px;
                font-weight: 650;
            }
            """
        )

    def _worker(
        self,
        function: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        worker = ApiWorker(function)
        worker.signals.finished.connect(on_success)
        worker.signals.failed.connect(on_error or self._task_failed)
        self.pool.start(worker)

    def _say(self, text: str, *, importance: str = "normal") -> None:
        if not text.strip():
            return
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/speech/event",
                payload={
                    "text": text,
                    "importance": importance,
                    "user_initiated": True,
                    "action_required": False,
                    "sensitive": False,
                },
                timeout=4,
            ),
            lambda _result: None,
            on_error=lambda _message: None,
        )

    def _history_add(self, text: str) -> None:
        stamp = time.strftime("%H:%M")
        self.activity_history.append(f"{stamp} · {text}")
        self.activity_history = self.activity_history[-4:]
        self.activity_log.setText("\n".join(self.activity_history))
        self.activity_log.setVisible(bool(self.activity_history))

    def announce(self, text: str, *, speak: bool = True, add_history: bool = True) -> None:
        self.caption.setText(text)
        self.left_state.setText(text)
        if add_history:
            self._history_add(text)
        if speak:
            self._say(text)

    def begin_activity(self, text: str, *, wait_text: str | None = None) -> int:
        self.activity_serial += 1
        serial = self.activity_serial
        self.busy = True
        self.activity_started_at = time.monotonic()
        self.activity_title.setText("Je m’en occupe")
        self.activity_detail.setText(text)
        self.activity_progress.show()
        self.status.setText("●  Jarvis travaille…")
        self._history_add(text)
        self._say(text)
        self.caption.setText(text)
        self.left_state.setText(text)
        if wait_text:
            QTimer.singleShot(3200, partial(self._maybe_wait_update, serial, wait_text))
        return serial

    def _maybe_wait_update(self, serial: int, text: str) -> None:
        if not self.busy or serial != self.activity_serial:
            return
        self.activity_detail.setText(text)
        self._history_add(text)
        self._say(text)
        self.caption.setText(text)

    def finish_activity(self, text: str, *, success: bool = True, speak: bool = True) -> None:
        self.busy = False
        self.activity_started_at = None
        self.activity_progress.hide()
        self.activity_elapsed.setText("")
        self.activity_title.setText("Terminé" if success else "J’ai besoin de ton aide")
        self.activity_detail.setText(text)
        self.status.setText("●  Jarvis est prêt" if success else "●  À vérifier")
        self._history_add(text)
        self.caption.setText(text)
        self.left_state.setText(text)
        if speak:
            self._say(text, importance="high" if not success else "normal")
        QTimer.singleShot(500, self.refresh)

    def _update_activity_elapsed(self) -> None:
        if not self.busy or self.activity_started_at is None:
            return
        elapsed = int(time.monotonic() - self.activity_started_at)
        if elapsed < 2:
            self.activity_elapsed.setText("")
        elif elapsed < 60:
            self.activity_elapsed.setText(f"depuis {elapsed} s")
        else:
            self.activity_elapsed.setText(f"depuis {elapsed // 60} min")

    def _task_failed(self, message: str) -> None:
        text = "Je n’ai pas pu terminer. Je te montre le problème pour qu’on décide quoi faire."
        self.finish_activity(text, success=False)
        QMessageBox.warning(self, "Jarvis", f"{text}\n\n{message}")

    def refresh(self) -> None:
        self._worker(
            lambda: self.api.request("GET", "/api/actions"),
            self._receive_cards,
            on_error=lambda _message: None,
        )
        self._worker(
            lambda: self.api.request("GET", "/api/newsletters"),
            self.render_newsletters,
            on_error=lambda _message: None,
        )

    def refresh_diagnostics(self) -> None:
        self._worker(
            lambda: self.api.request("GET", "/api/diagnostics"),
            self._apply_diagnostics,
            on_error=lambda _message: self.status.setText("●  Jarvis fonctionne en mode limité"),
        )

    def _apply_diagnostics(self, report: dict[str, object]) -> None:
        errors = int(report.get("errors") or 0)
        warnings = int(report.get("warnings") or 0)
        if errors:
            self.status.setText("●  Jarvis a besoin d’une vérification")
        elif warnings:
            self.status.setText("●  Jarvis est prêt · mode dégradé")
        elif not self.busy:
            self.status.setText("●  Jarvis est prêt")

    def render_newsletters(self, payload: dict[str, object]) -> None:
        self.newsletter_count = int(payload.get("count") or 0)
        suffix = "newsletter à ranger" if self.newsletter_count == 1 else "newsletters à ranger"
        self.newsletter_label.setText(f"{self.newsletter_count} {suffix}")

    def _receive_cards(self, cards: list[dict[str, object]]) -> None:
        self.latest_cards = cards
        self.render_proposals(cards)
        self.render_cards(cards)
        if not self.intro_announced:
            self.intro_announced = True
            QTimer.singleShot(450, self._announce_intro)

    def _announce_intro(self) -> None:
        count = min(len(self.latest_cards), 3)
        if count:
            text = (
                f"Bonjour {settings.user_name}. J’ai repéré {count} chose"
                f"{'s' if count > 1 else ''} qui mérite{'nt' if count > 1 else ''} ton attention. "
                "Je t’ai préparé plusieurs choix. Tu peux en sélectionner une ou plusieurs. On commence par quoi ?"
            )
        else:
            text = (
                f"Bonjour {settings.user_name}. Tout est calme pour le moment. "
                "Je peux vérifier tes mails ou retrouver un document. Tu peux choisir plusieurs options. On commence par quoi ?"
            )
        self.announce(text, speak=True, add_history=False)

    def _proposal_label(self, card: dict[str, object]) -> str:
        metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
        recommendation = str(metadata.get("recommended_action") or "").strip()
        title = str(card.get("title") or "À vérifier").strip()
        if recommendation:
            return f"{title}\n→ {recommendation}"
        return title

    def render_proposals(self, cards: list[dict[str, object]]) -> None:
        previous = {key for key, checkbox in self.proposal_checks.items() if checkbox.isChecked()}
        while self.proposals_layout.count():
            item = self.proposals_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.proposal_checks.clear()

        proposals: list[tuple[str, str]] = []
        for card in cards[:3]:
            card_id = str(card.get("id") or "")
            if card_id:
                proposals.append((f"card:{card_id}", self._proposal_label(card)))
        if len(proposals) < 3:
            proposals.append(("app:thunderbird", "Voir mes mails importants"))
        if len(proposals) < 3:
            proposals.append(("app:explorer", "Retrouver ou ouvrir un document"))
        if len(proposals) < 3 and self.newsletter_count:
            proposals.append(("newsletters", "Ranger les newsletters détectées"))
        proposals = proposals[:4]

        for key, label in proposals:
            frame = QFrame()
            frame.setObjectName("proposalCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(5, 5, 5, 5)
            checkbox = QCheckBox(label)
            checkbox.setWordWrap(True) if hasattr(checkbox, "setWordWrap") else None
            checkbox.setChecked(key in previous)
            layout.addWidget(checkbox)
            self.proposal_checks[key] = checkbox
            self.proposals_layout.addWidget(frame, 1)

    def start_selected_proposals(self) -> None:
        selected = [key for key, checkbox in self.proposal_checks.items() if checkbox.isChecked()]
        if not selected:
            text = "Choisis simplement une ou plusieurs propositions, puis je m’occupe de la suite."
            self.announce(text)
            return

        card_ids = {key.split(":", 1)[1] for key in selected if key.startswith("card:")}
        self.selected_card_ids = card_ids
        self.render_cards(self.latest_cards)

        labels: list[str] = []
        for key in selected:
            checkbox = self.proposal_checks[key]
            labels.append(checkbox.text().split("\n", 1)[0])

        if len(labels) == 1:
            message = f"Très bien. On commence par : {labels[0]}."
        else:
            message = f"Très bien. Tu as choisi {len(labels)} choses. Je les garde toutes sous les yeux."
        self.announce(message)

        for key in selected:
            if key == "app:thunderbird":
                self.start_app("thunderbird")
                break
            if key == "app:explorer":
                self.start_app("explorer")
                break
            if key == "newsletters":
                self.sort_newsletters()
                break

    def show_all_cards(self) -> None:
        self.selected_card_ids.clear()
        self.render_cards(self.latest_cards)
        self.announce("Je réaffiche toutes les choses qui méritent ton attention.")

    def render_cards(self, cards: list[dict[str, object]]) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if self.selected_card_ids:
            visible = [card for card in cards if str(card.get("id") or "") in self.selected_card_ids]
            self.section.setText("Tes choix")
            self.show_all_button.show()
        else:
            visible = cards[:3]
            self.section.setText("Détails et choix")
            self.show_all_button.setVisible(len(cards) > 3)

        if not visible:
            empty = QLabel(
                "Rien d’urgent à traiter. Je continuerai à surveiller et je te proposerai quelque chose seulement si c’est utile."
            )
            empty.setWordWrap(True)
            empty.setObjectName("muted")
            empty.setStyleSheet(
                "padding: 24px; background:#ffffff; border:1px dashed #c7d6e5; border-radius:16px;"
            )
            self.cards_layout.addWidget(empty)
        for card in visible:
            self.cards_layout.addWidget(self._card_widget(card))
        self.cards_layout.addSpacerItem(
            QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

    def _card_widget(self, card: dict[str, object]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("taskCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 17, 20, 17)
        layout.setSpacing(8)

        title = QLabel(str(card.get("title") or "À vérifier"))
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        source = QLabel(str(card.get("source") or ""))
        source.setObjectName("muted")
        layout.addWidget(source)

        summary = QLabel(str(card.get("summary") or ""))
        summary.setObjectName("cardSummary")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
        recommendation = str(metadata.get("recommended_action") or "")
        if recommendation:
            label = QLabel(f"Mon conseil : {recommendation}")
            label.setObjectName("recommendation")
            label.setWordWrap(True)
            layout.addWidget(label)

        deadline = str(metadata.get("deadline_text") or "")
        if deadline:
            label = QLabel(f"Échéance : {deadline}")
            label.setObjectName("deadline")
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            layout.addWidget(label)

        options = card.get("options") if isinstance(card.get("options"), list) else []
        actions = QHBoxLayout()
        for index, option in enumerate(options[:3]):
            if not isinstance(option, dict):
                continue
            button = QPushButton(str(option.get("label") or "Continuer"))
            if index == 0:
                button.setObjectName("primaryButton")
            button.clicked.connect(partial(self.handle_option, card, option))
            actions.addWidget(button, 1)
        if len(options) < 3:
            later = QPushButton("Plus tard")
            later.clicked.connect(partial(self.snooze_card, str(card.get("id") or "")))
            actions.addWidget(later, 1)
        layout.addLayout(actions)
        return frame

    def start_app(self, name: str) -> None:
        friendly = "Thunderbird et tes mails" if name == "thunderbird" else "tes documents"
        self.begin_activity(
            f"J’ouvre {friendly}.",
            wait_text="L’ouverture prend un peu plus de temps que prévu, mais je continue.",
        )
        self._worker(
            lambda: self.api.request("POST", "/api/desktop/start", payload={"app": name}),
            partial(self._operation_result, f"C’est fait. J’ai ouvert {friendly}."),
        )

    def _operation_result(self, done_text: str, result: dict[str, object]) -> None:
        detail = str(result.get("detail") or "")
        if not bool(result.get("ok", True)):
            self._task_failed(detail or "L’action n’a pas abouti.")
            return
        self.finish_activity(detail or done_text)

    def handle_option(self, card: dict[str, object], option: dict[str, object]) -> None:
        card_id = str(card.get("id") or "")
        option_id = str(option.get("id") or "")
        kind = str(option.get("kind") or "")
        option_label = str(option.get("label") or "cette action")

        token = ""
        if bool(option.get("requires_confirmation")):
            token = self.authorize(
                "mail.prepare_reply",
                "Préparer un brouillon dans Thunderbird. Aucun mail ne sera envoyé.",
            ) or ""
            if not token:
                return

        starts = {
            "search_files": "Je cherche les documents qui correspondent. Je vérifie d’abord les emplacements les plus probables.",
            "open_email": "J’ouvre le message dans Thunderbird pour que tu puisses le voir.",
            "send_reply": "Je prépare le brouillon demandé. Je ne l’enverrai pas sans ton accord.",
        }
        start_text = starts.get(kind, f"Tu as choisi « {option_label} ». Je m’en occupe maintenant.")
        self.begin_activity(
            start_text,
            wait_text="Ça peut prendre quelques instants. Je continue et je te préviens dès que j’ai le résultat.",
        )

        payload: dict[str, object] = {"option_id": option_id}
        if token:
            payload["authorization_token"] = token
        self._worker(
            lambda: self.api.request(
                "POST",
                f"/api/actions/{card_id}/execute",
                payload=payload,
                timeout=30,
            ),
            partial(self._option_result, card, kind),
        )

    def _option_result(
        self,
        card: dict[str, object],
        kind: str,
        result: dict[str, object],
    ) -> None:
        if not bool(result.get("ok", False)):
            self._task_failed(str(result.get("detail") or result.get("reason") or "Action bloquée."))
            return
        if kind == "search_files":
            items = result.get("results") if isinstance(result.get("results"), list) else []
            if not items:
                self.finish_activity(
                    "Je n’ai pas trouvé de document correspondant. Je n’ai rien modifié."
                )
                return
            self.finish_activity(
                f"J’ai trouvé {len(items)} document{'s' if len(items) > 1 else ''}. Je te les affiche pour que tu choisisses."
            )
            self.choose_file(card, items)
            return
        detail = str(result.get("detail") or "")
        self.finish_activity(detail or "C’est fait. L’étape est terminée.")

    def choose_file(self, card: dict[str, object], results: list[dict[str, object]]) -> None:
        dialog = FileChoiceDialog(results, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_path:
            self.announce("D’accord. Je n’ouvre rien pour le moment.")
            return
        filename = Path(dialog.selected_path).name
        if dialog.mode == "open":
            self.begin_activity(f"J’ouvre le document « {filename} ».")
            self._worker(
                lambda: self.api.request(
                    "POST", "/api/files/open", payload={"path": dialog.selected_path}
                ),
                partial(self._operation_result, f"C’est fait. Le document « {filename} » est ouvert."),
            )
            return
        if dialog.mode == "attach":
            token = self.authorize(
                "mail.prepare_reply_attachment",
                f"Préparer un brouillon avec le document « {filename} ».",
            )
            if not token:
                return
            card_id = str(card.get("id") or "")
            self.begin_activity(
                f"Je prépare le brouillon avec « {filename} » en pièce jointe.",
                wait_text="Je prépare la pièce jointe et le brouillon. Ça peut prendre quelques instants.",
            )
            self._worker(
                lambda: self.api.request(
                    "POST",
                    f"/api/actions/{card_id}/attach",
                    payload={"paths": [dialog.selected_path], "authorization_token": token},
                    timeout=30,
                ),
                partial(self._operation_result, "Le brouillon est prêt avec le document joint."),
            )

    def snooze_card(self, card_id: str) -> None:
        if not card_id:
            return
        token = self.authorize(
            "actions.snooze",
            "Reporter cette tâche de quatre heures. Elle réapparaîtra automatiquement.",
        )
        if not token:
            return
        self.begin_activity("Je reporte cette tâche de quatre heures.")
        self._worker(
            lambda: self.api.request(
                "POST",
                f"/api/actions/{card_id}/snooze",
                payload={"hours": 4, "authorization_token": token},
            ),
            partial(self._operation_result, "C’est fait. Je te la reproposerai dans quatre heures."),
        )

    def sort_newsletters(self) -> None:
        if self.newsletter_count <= 0:
            self.announce("Il n’y a aucune newsletter à ranger pour le moment.")
            return
        token = self.authorize(
            "mail.sort_newsletters",
            "Déplacer les newsletters détectées dans le dossier Newsletters de Thunderbird.",
        )
        if not token:
            return
        self.begin_activity(
            "Je range les newsletters détectées dans Thunderbird.",
            wait_text="Je continue le rangement. Cela peut prendre quelques instants si plusieurs messages sont concernés.",
        )
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/newsletters/sort",
                payload={"authorization_token": token},
            ),
            partial(self._operation_result, "C’est fait. Les newsletters sont rangées."),
        )

    def authorize(self, action_key: str, description: str) -> str | None:
        self.announce(
            "Cette action va modifier quelque chose. J’ai besoin de ta première autorisation avant de continuer."
        )
        first = QMessageBox.question(
            self,
            "Autorisation 1 sur 2",
            f"Première autorisation\n\n{description}\n\nVeux-tu continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if first != QMessageBox.StandardButton.Yes:
            self.announce("D’accord. J’arrête ici et je ne modifie rien.")
            return None
        try:
            started = self.api.request(
                "POST",
                "/api/confirmations/start",
                payload={"action_key": action_key, "description": description},
                timeout=4,
            )
            challenge_id = str(started.get("challenge_id") or "")
            step_one = self.api.request(
                "POST", f"/api/confirmations/{challenge_id}/confirm", payload={}, timeout=4
            )
            if not bool(step_one.get("ok")):
                raise RuntimeError("La première autorisation n’a pas été enregistrée.")
        except Exception as exc:
            self._task_failed(str(exc))
            return None

        self.announce(
            "Première autorisation enregistrée. Il me faut maintenant ta seconde autorisation, séparément."
        )
        second = QMessageBox.question(
            self,
            "Autorisation 2 sur 2",
            f"Seconde autorisation\n\n{description}\n\nConfirmes-tu une seconde fois ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if second != QMessageBox.StandardButton.Yes:
            self.announce("D’accord. La seconde autorisation n’a pas été donnée : je ne modifie rien.")
            return None
        try:
            step_two = self.api.request(
                "POST", f"/api/confirmations/{challenge_id}/confirm", payload={}, timeout=4
            )
        except Exception as exc:
            self._task_failed(str(exc))
            return None
        token = step_two.get("authorization_token")
        if not bool(step_two.get("completed")) or not isinstance(token, str) or not token:
            self._task_failed("La double autorisation n’a pas été validée.")
            return None
        self.announce("Merci. Les deux autorisations sont validées. Je peux maintenant exécuter cette action.")
        return token

    def poll_voice(self) -> None:
        self._worker(
            lambda: self.api.request(
                "GET", "/api/voice/events", params={"after": self.last_voice_event}, timeout=3
            ),
            self._voice_events,
            on_error=lambda _message: None,
        )

    def _voice_events(self, payload: dict[str, object]) -> None:
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        if not events:
            return
        event = events[-1]
        if not isinstance(event, dict):
            return
        self.last_voice_event = max(self.last_voice_event, int(event.get("id") or 0))
        text = str(event.get("text") or "Je te parle.")
        duration = max(1.6, float(event.get("duration_estimate_seconds") or 2.0))
        self.caption.setText(text)
        self.avatar.set_speaking(True)
        self.speaking_timer.start(int((duration + 0.5) * 1000))

    def _stop_speaking(self) -> None:
        self.avatar.set_speaking(False)
        if self.busy:
            self.caption.setText(self.activity_detail.text())
        else:
            self.caption.setText("Je suis prêt. Dis-moi simplement ce que tu veux choisir.")


def run() -> None:
    """Start the proactive native Windows experience and its hidden localhost bridge."""

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setOrganizationName("Jarvis Papa")
    app.setFont(QFont("Segoe UI", 10))

    from PySide6.QtCore import QLockFile

    lock = QLockFile(str((settings.runtime_dir / "jarvis-desktop.lock").resolve()))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Jarvis", "Jarvis est déjà ouvert sur cet ordinateur.")
        return

    backend = BackendService()
    if not backend.start():
        QMessageBox.critical(
            None,
            "Jarvis",
            "Jarvis n’a pas pu démarrer son service local. Redémarre l’application ou lance le diagnostic.",
        )
        lock.unlock()
        return

    window = ProfessionalMainWindow()
    window.show()
    exit_code = app.exec()
    backend.stop()
    lock.unlock()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    run()
