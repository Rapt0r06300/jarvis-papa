from __future__ import annotations

import html
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from jarvis_papa.config import settings
from jarvis_papa.desktop_app import ApiClient, ApiWorker, AvatarWidget, BackendService, FileChoiceDialog


class ProfessionalMainWindow(QMainWindow):
    """Proactive, conversational and transparent supervision surface for Jarvis."""

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
        self.conversation_id = uuid4().hex
        self.active_request_id: str | None = None

        self.speaking_timer = QTimer(self)
        self.speaking_timer.setSingleShot(True)
        self.speaking_timer.timeout.connect(self._stop_speaking)

        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self._update_activity_elapsed)
        self.activity_timer.start(1000)

        self.setWindowTitle("Jarvis · Assistant personnel")
        self.setMinimumSize(1080, 720)
        self.resize(1240, 860)
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
        QTimer.singleShot(550, self.refresh_capabilities)
        QTimer.singleShot(700, self.chat_input.setFocus)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        assistant_panel = QFrame()
        assistant_panel.setObjectName("assistantPanel")
        assistant_panel.setMinimumWidth(300)
        assistant_panel.setMaximumWidth(380)
        assistant_layout = QVBoxLayout(assistant_panel)
        assistant_layout.setContentsMargins(24, 24, 24, 26)
        assistant_layout.addStretch(1)

        self.avatar = AvatarWidget()
        assistant_layout.addWidget(self.avatar, 5)

        self.caption = QLabel("Je démarre et je regarde ce qui mérite ton attention.")
        self.caption.setWordWrap(True)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setObjectName("caption")
        self.caption.setAccessibleName("Ce que Jarvis est en train de dire ou de faire")
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
        content_layout.setContentsMargins(30, 24, 30, 22)
        content_layout.setSpacing(12)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        self.hello = QLabel(f"Bonjour {settings.user_name}")
        self.hello.setObjectName("hello")
        subtitle = QLabel("Je suis là. Tu peux me parler naturellement ou choisir une proposition.")
        subtitle.setObjectName("muted")
        identity.addWidget(self.hello)
        identity.addWidget(subtitle)
        header.addLayout(identity)
        header.addStretch(1)
        self.status = QLabel("●  Démarrage…")
        self.status.setObjectName("status")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignTop)
        content_layout.addLayout(header)

        conversation_frame = QFrame()
        conversation_frame.setObjectName("conversationPanel")
        conversation_layout = QVBoxLayout(conversation_frame)
        conversation_layout.setContentsMargins(20, 16, 20, 18)
        conversation_layout.setSpacing(9)

        conversation_head = QHBoxLayout()
        conversation_title = QLabel("Parler à Jarvis")
        conversation_title.setObjectName("conversationTitle")
        conversation_head.addWidget(conversation_title)
        conversation_head.addStretch(1)
        self.chat_state = QLabel("Prêt à répondre")
        self.chat_state.setObjectName("chatState")
        conversation_head.addWidget(self.chat_state)
        conversation_layout.addLayout(conversation_head)

        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("conversationHistory")
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_view.setMinimumHeight(105)
        self.chat_view.setMaximumHeight(190)
        self.chat_view.setAccessibleName("Conversation avec Jarvis")
        self.chat_view.setHtml(
            "<div class='jarvisBubble'><b>Jarvis</b><br>"
            "Tu peux me demander ce que tu veux. Je te dirai clairement ce que je sais, "
            "ce que je cherche et ce que je fais.</div>"
        )
        conversation_layout.addWidget(self.chat_view)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.chat_input = QLineEdit()
        self.chat_input.setObjectName("chatInput")
        self.chat_input.setPlaceholderText("Demandez quelque chose à Jarvis…")
        self.chat_input.setClearButtonEnabled(True)
        self.chat_input.setMinimumHeight(58)
        self.chat_input.setAccessibleName("Demande à Jarvis")
        self.chat_input.setAccessibleDescription(
            "Écris une demande en langage naturel puis appuie sur Entrée ou sur Envoyer."
        )
        self.chat_input.returnPressed.connect(self.send_chat)
        input_row.addWidget(self.chat_input, 1)

        self.mic_button = QPushButton("🎤")
        self.mic_button.setObjectName("micButton")
        self.mic_button.setToolTip("Microphone non configuré")
        self.mic_button.setAccessibleName("Parler à Jarvis avec le microphone")
        self.mic_button.hide()
        input_row.addWidget(self.mic_button)

        self.stop_chat_button = QPushButton("Arrêter")
        self.stop_chat_button.setObjectName("stopButton")
        self.stop_chat_button.setAccessibleName("Arrêter la demande en cours")
        self.stop_chat_button.clicked.connect(self.cancel_chat)
        self.stop_chat_button.hide()
        input_row.addWidget(self.stop_chat_button)

        self.send_chat_button = QPushButton("Envoyer")
        self.send_chat_button.setObjectName("primaryButton")
        self.send_chat_button.setAccessibleName("Envoyer la demande à Jarvis")
        self.send_chat_button.clicked.connect(self.send_chat)
        input_row.addWidget(self.send_chat_button)
        conversation_layout.addLayout(input_row)
        content_layout.addWidget(conversation_frame)

        proposal_frame = QFrame()
        proposal_frame.setObjectName("proposalPanel")
        proposal_layout = QVBoxLayout(proposal_frame)
        proposal_layout.setContentsMargins(18, 14, 18, 14)
        proposal_layout.setSpacing(8)

        proposal_head = QHBoxLayout()
        proposal_titles = QVBoxLayout()
        self.proposal_title = QLabel("Ce qui mérite ton attention")
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
        self.proposals_layout.setContentsMargins(0, 3, 0, 0)
        self.proposals_layout.setSpacing(8)
        proposal_layout.addWidget(self.proposals_container)
        content_layout.addWidget(proposal_frame)

        activity_frame = QFrame()
        activity_frame.setObjectName("activityPanel")
        activity_layout = QVBoxLayout(activity_frame)
        activity_layout.setContentsMargins(16, 12, 16, 12)
        activity_layout.setSpacing(6)

        activity_head = QHBoxLayout()
        self.activity_title = QLabel("Je suis prêt")
        self.activity_title.setObjectName("activityTitle")
        self.activity_elapsed = QLabel("")
        self.activity_elapsed.setObjectName("activityElapsed")
        activity_head.addWidget(self.activity_title)
        activity_head.addStretch(1)
        activity_head.addWidget(self.activity_elapsed)
        activity_layout.addLayout(activity_head)

        self.activity_detail = QLabel("Quand je travaille, je t’explique ce que je fais ici.")
        self.activity_detail.setWordWrap(True)
        self.activity_detail.setObjectName("activityDetail")
        self.activity_detail.setAccessibleName("Activité actuelle de Jarvis")
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
        self.section = QLabel("Actions simples")
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
        self.cards_layout.setSpacing(10)
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
            #hello { font-size: 35px; font-weight: 750; color: #15263e; }
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
            #conversationPanel {
                background: #ffffff;
                border: 1px solid #cbdbea;
                border-radius: 20px;
            }
            #conversationTitle { font-size: 24px; font-weight: 780; color: #172d49; }
            #chatState { color: #58718c; font-size: 14px; font-weight: 650; }
            #conversationHistory {
                background: #f4f8fd;
                border: 1px solid #dbe6f1;
                border-radius: 14px;
                padding: 9px 12px;
                color: #263b54;
                selection-background-color: #b9d8f5;
            }
            #chatInput {
                background: #ffffff;
                border: 2px solid #b8cce0;
                border-radius: 15px;
                padding: 0 16px;
                font-size: 18px;
                color: #172338;
            }
            #chatInput:focus { border-color: #1769bd; }
            #proposalPanel {
                background: #ffffff;
                border: 1px solid #d6e2ef;
                border-radius: 18px;
            }
            #proposalTitle { font-size: 21px; font-weight: 750; color: #172d49; }
            #proposalCard {
                background: #f7fbff;
                border: 1px solid #d5e5f4;
                border-radius: 15px;
            }
            QCheckBox {
                spacing: 10px;
                font-size: 16px;
                font-weight: 650;
                color: #213a58;
                padding: 10px;
                min-height: 48px;
            }
            QCheckBox::indicator {
                width: 23px;
                height: 23px;
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
                border-radius: 17px;
            }
            #activityTitle { color: #ffffff; font-size: 18px; font-weight: 750; }
            #activityElapsed { color: #c7d9eb; font-size: 14px; }
            #activityDetail { color: #e2edf8; font-size: 15px; }
            #activityLog { color: #b8cde2; font-size: 13px; }
            QProgressBar { border: none; background: #294968; border-radius: 4px; }
            QProgressBar::chunk { background: #64b5ff; border-radius: 4px; }
            #sectionTitle { font-size: 20px; font-weight: 750; margin-top: 2px; }
            QPushButton {
                min-height: 48px;
                padding: 0 18px;
                border-radius: 13px;
                border: 1px solid #c9d6e4;
                background: #ffffff;
                color: #1d3552;
                font-weight: 650;
            }
            QPushButton:hover { background: #f0f6fc; border-color: #9bb6cf; }
            QPushButton:focus { border: 2px solid #1769bd; }
            QPushButton:pressed { background: #e7f0f9; }
            QPushButton:disabled { color: #95a2b2; background: #eef2f6; }
            #primaryButton {
                background: #1769bd;
                color: white;
                border-color: #1769bd;
                font-weight: 750;
            }
            #primaryButton:hover { background: #105ba7; }
            #stopButton {
                background: #fff6f1;
                color: #8a3b18;
                border-color: #e8c7b5;
            }
            #micButton { min-width: 54px; max-width: 60px; padding: 0; font-size: 20px; }
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

    def _append_chat(self, speaker: str, text: str) -> None:
        safe = html.escape(" ".join(text.split())).replace("\n", "<br>")
        if speaker == "Robert":
            block = (
                "<div style='margin:6px 0 8px 12%; padding:9px 12px; background:#dfeefe; "
                "border-radius:12px; color:#17324f'><b>Vous</b><br>" + safe + "</div>"
            )
        else:
            block = (
                "<div style='margin:6px 12% 8px 0; padding:9px 12px; background:#ffffff; "
                "border:1px solid #d9e5f0; border-radius:12px; color:#263b54'><b>Jarvis</b><br>"
                + safe
                + "</div>"
            )
        self.chat_view.append(block)
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def send_chat(self) -> None:
        if self.active_request_id:
            self.chat_state.setText("Une demande est déjà en cours")
            return
        text = self.chat_input.text().strip()
        if not text:
            self.chat_input.setFocus()
            return
        request_id = uuid4().hex
        self.active_request_id = request_id
        self._append_chat("Robert", text)
        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.send_chat_button.setEnabled(False)
        self.stop_chat_button.show()
        self.chat_state.setText("Jarvis réfléchit…")
        self.begin_activity(
            "Je regarde ta demande et je choisis la façon la plus simple de t’aider.",
            wait_text="Je continue. Si j’ai besoin de vérifier plusieurs choses, cela peut prendre quelques instants.",
        )
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/conversation/turn",
                payload={
                    "text": text,
                    "conversation_id": self.conversation_id,
                    "request_id": request_id,
                    "speak": True,
                },
                timeout=45,
            ),
            partial(self._chat_result, request_id),
            on_error=partial(self._chat_failed, request_id),
        )

    def _chat_result(self, request_id: str, result: dict[str, object]) -> None:
        if request_id != self.active_request_id:
            return
        returned_conversation = str(result.get("conversation_id") or "")
        if returned_conversation:
            self.conversation_id = returned_conversation
        answer = str(result.get("answer") or "Je n’ai pas de réponse fiable pour le moment.")
        final_state = str(result.get("final_state") or "unknown")
        self._append_chat("Jarvis", answer)
        self.active_request_id = None
        self.chat_input.setEnabled(True)
        self.send_chat_button.setEnabled(True)
        self.stop_chat_button.hide()
        self.chat_state.setText("Prêt à répondre")
        self.chat_input.setFocus()
        if final_state == "cancelled":
            self.finish_activity("D’accord. J’ai arrêté cette demande.", speak=False)
        elif final_state == "failed":
            self.finish_activity(answer, success=False, speak=False)
        elif final_state == "partial":
            self.finish_activity(answer, success=True, speak=False)
        else:
            self.finish_activity(answer, success=True, speak=False)

    def _chat_failed(self, request_id: str, _message: str) -> None:
        if request_id != self.active_request_id:
            return
        self.active_request_id = None
        self.chat_input.setEnabled(True)
        self.send_chat_button.setEnabled(True)
        self.stop_chat_button.hide()
        self.chat_state.setText("Prêt à réessayer")
        answer = "Je n’ai pas pu répondre cette fois. Tu peux réessayer, je reste disponible."
        self._append_chat("Jarvis", answer)
        self.finish_activity(answer, success=False, speak=True)
        self.chat_input.setFocus()

    def cancel_chat(self) -> None:
        request_id = self.active_request_id
        if not request_id:
            return
        self.chat_state.setText("J’arrête la demande…")
        self.stop_chat_button.setEnabled(False)
        self._worker(
            lambda: self.api.request(
                "POST",
                f"/api/conversation/{self.conversation_id}/cancel",
                payload={"request_id": request_id},
                timeout=4,
            ),
            self._cancel_result,
            on_error=lambda _message: self.stop_chat_button.setEnabled(True),
        )

    def _cancel_result(self, result: dict[str, object]) -> None:
        self.stop_chat_button.setEnabled(True)
        if bool(result.get("ok")):
            self.chat_state.setText("Arrêt demandé…")
            self.activity_detail.setText("J’arrête proprement la demande en cours.")
        else:
            self.chat_state.setText("La demande se termine…")

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

    def refresh_capabilities(self) -> None:
        self._worker(
            lambda: self.api.request("GET", "/api/status", timeout=3),
            self._apply_capabilities,
            on_error=lambda _message: None,
        )

    def _apply_capabilities(self, payload: dict[str, object]) -> None:
        modules = payload.get("modules") if isinstance(payload.get("modules"), dict) else {}
        voice_input = str(modules.get("voice_input") or "")
        enabled = voice_input not in {"", "disabled_no_microphone", "unavailable"}
        self.mic_button.setVisible(enabled)
        self.mic_button.setEnabled(enabled)
        if enabled:
            self.mic_button.setToolTip("Maintenir pour parler à Jarvis")

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
                "Tu peux me parler directement, ou choisir une ou plusieurs propositions."
            )
        else:
            text = (
                f"Bonjour {settings.user_name}. Tout est calme pour le moment. "
                "Tu peux simplement m’écrire ce que tu veux faire ou ce que tu veux savoir."
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
            self.section.setText("Actions simples")
            self.show_all_button.setVisible(len(cards) > 3)

        if not visible:
            empty = QLabel(
                "Rien d’urgent à traiter. Je continuerai à surveiller et je te proposerai quelque chose seulement si c’est utile."
            )
            empty.setWordWrap(True)
            empty.setObjectName("muted")
            empty.setStyleSheet(
                "padding: 22px; background:#ffffff; border:1px dashed #c7d6e5; border-radius:16px;"
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
            partial(self._operation_result, f"J’ai ouvert {friendly}."),
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
        self.finish_activity(detail or "L’étape est terminée.")

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
                partial(self._operation_result, f"Le document « {filename} » est ouvert."),
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
            partial(self._operation_result, "Je te la reproposerai dans quatre heures."),
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
            partial(self._operation_result, "Le rangement a été demandé à Thunderbird."),
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
            f"Dernière confirmation\n\n{description}\n\nVeux-tu vraiment continuer ?",
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
            self.caption.setText("Je suis prêt. Écris-moi ce que tu veux, ou choisis une proposition.")


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
