from __future__ import annotations

import math
import sys
import threading
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable

import httpx
import uvicorn
from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from jarvis_papa.config import settings


class ApiClient:
    def __init__(self) -> None:
        self.base_url = f"http://{settings.host}:{settings.port}"

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        timeout: float = 12.0,
    ) -> Any:
        with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
            response = client.request(method, path, json=payload, params=params)
            response.raise_for_status()
            return response.json()


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class ApiWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # UI boundary: surface the failure instead of crashing Qt.
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


class BackendService:
    """Run Jarvis' localhost API invisibly for Thunderbird and the native desktop UI."""

    def __init__(self) -> None:
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> bool:
        from jarvis_papa.app import app

        config = uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run,
            name="jarvis-local-api",
            daemon=True,
        )
        self.thread.start()

        deadline = time.monotonic() + 12.0
        url = f"http://{settings.host}:{settings.port}/health"
        while time.monotonic() < deadline:
            if self.thread and not self.thread.is_alive():
                return False
            try:
                response = httpx.get(url, timeout=0.5)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(0.15)
        return False

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=3)


class AvatarWidget(QWidget):
    """Native vector avatar: no browser engine, image server, or WebView required."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(260, 315)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.speaking = False
        self.phase = 0.0
        self.blink = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(90)

    def set_speaking(self, value: bool) -> None:
        self.speaking = value
        self.update()

    def _tick(self) -> None:
        self.phase += 0.38 if self.speaking else 0.08
        cycle = self.phase % 19.0
        self.blink = 1.0 if 17.9 < cycle < 18.35 else 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())
        scale = min(width / 300.0, height / 340.0)
        ox = (width - 300.0 * scale) / 2.0
        oy = (height - 340.0 * scale) / 2.0
        painter.translate(ox, oy)
        painter.scale(scale, scale)

        # Soft halo behind the assistant.
        halo = QLinearGradient(70, 20, 230, 310)
        halo.setColorAt(0, QColor("#e5f1ff"))
        halo.setColorAt(1, QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(150, 165), 132, 150)

        # Shoulders and blouse.
        painter.setBrush(QColor("#e8e2dc"))
        painter.drawRoundedRect(68, 270, 164, 78, 40, 40)
        painter.setBrush(QColor("#f5f7fb"))
        painter.drawRoundedRect(88, 275, 124, 70, 30, 30)

        # Hair mass.
        hair = QLinearGradient(80, 45, 220, 245)
        hair.setColorAt(0, QColor("#624238"))
        hair.setColorAt(1, QColor("#2f211f"))
        painter.setBrush(hair)
        painter.drawEllipse(QPointF(150, 145), 78, 116)

        # Face.
        skin = QLinearGradient(110, 70, 185, 235)
        skin.setColorAt(0, QColor("#f3ccb0"))
        skin.setColorAt(1, QColor("#e8b798"))
        painter.setBrush(skin)
        painter.drawEllipse(QPointF(150, 155), 61, 82)

        # Hair fringe.
        fringe = QPainterPath()
        fringe.moveTo(92, 132)
        fringe.cubicTo(88, 72, 118, 42, 153, 42)
        fringe.cubicTo(190, 42, 215, 73, 213, 112)
        fringe.cubicTo(184, 105, 163, 84, 153, 62)
        fringe.cubicTo(139, 91, 120, 119, 92, 132)
        painter.setBrush(hair)
        painter.drawPath(fringe)

        # Brows.
        painter.setPen(QPen(QColor("#6a4438"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(116, 140, 142, 137)
        painter.drawLine(160, 137, 185, 140)

        # Eyes with an occasional natural blink.
        if self.blink:
            painter.setPen(QPen(QColor("#76554a"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(120, 157, 140, 157)
            painter.drawLine(161, 157, 181, 157)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QPointF(130, 157), 10, 7)
            painter.drawEllipse(QPointF(171, 157), 10, 7)
            painter.setBrush(QColor("#6a4a3b"))
            painter.drawEllipse(QPointF(131, 157), 4.8, 4.8)
            painter.drawEllipse(QPointF(170, 157), 4.8, 4.8)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QPointF(132.5, 155.5), 1.3, 1.3)
            painter.drawEllipse(QPointF(171.5, 155.5), 1.3, 1.3)

        # Nose and mouth.
        painter.setPen(QPen(QColor("#cf9579"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(150, 164, 153, 188)
        painter.setPen(QPen(QColor("#a55458"), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(132, 197, 38, 22, 200 * 16, 140 * 16)
        if self.speaking:
            mouth_height = 5.5 + 5.0 * abs(math.sin(self.phase * 1.8))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#8d4249"))
            painter.drawEllipse(QPointF(151, 214), 14, mouth_height)

        # Small voice bars.
        base_y = 292
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(5):
            amplitude = 8
            if self.speaking:
                amplitude = 10 + int(13 * abs(math.sin(self.phase + index * 0.7)))
            painter.setBrush(QColor("#2b75c7") if self.speaking else QColor("#bfd4e8"))
            painter.drawRoundedRect(126 + index * 12, base_y - amplitude / 2, 5, amplitude, 2, 2)


class FileChoiceDialog(QDialog):
    def __init__(self, results: list[dict[str, object]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.results = results
        self.selected_path: str | None = None
        self.mode: str | None = None
        self.setWindowTitle("Documents trouvés")
        self.resize(650, 420)
        layout = QVBoxLayout(self)
        title = QLabel("J’ai trouvé ces documents")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        note = QLabel("Choisis simplement le bon fichier.")
        note.setObjectName("muted")
        layout.addWidget(note)
        self.list_widget = QListWidget()
        for item in results:
            path = str(item.get("path") or item.get("name") or "Document")
            self.list_widget.addItem(path)
        if results:
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget, 1)
        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        open_button = QPushButton("Ouvrir")
        open_button.clicked.connect(partial(self._choose, "open"))
        attach_button = QPushButton("Préparer la réponse avec ce document")
        attach_button.setObjectName("primaryButton")
        attach_button.clicked.connect(partial(self._choose, "attach"))
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(open_button)
        buttons.addWidget(attach_button)
        layout.addLayout(buttons)

    def _choose(self, mode: str) -> None:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.results):
            return
        self.mode = mode
        self.selected_path = str(self.results[row].get("path") or "")
        if self.selected_path:
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.api = ApiClient()
        self.pool = QThreadPool.globalInstance()
        self.last_voice_event = 0
        self.speaking_timer = QTimer(self)
        self.speaking_timer.setSingleShot(True)
        self.speaking_timer.timeout.connect(self._stop_speaking)
        self.setWindowTitle("Jarvis")
        self.setMinimumSize(1020, 680)
        self.resize(1180, 760)
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
        assistant_panel.setMinimumWidth(315)
        assistant_panel.setMaximumWidth(385)
        assistant_layout = QVBoxLayout(assistant_panel)
        assistant_layout.setContentsMargins(22, 22, 22, 24)
        assistant_layout.addStretch(1)
        self.avatar = AvatarWidget()
        assistant_layout.addWidget(self.avatar, 4)
        self.caption = QLabel("Je suis prête. Je te parlerai seulement quand c’est utile.")
        self.caption.setWordWrap(True)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setObjectName("caption")
        assistant_layout.addWidget(self.caption)
        assistant_layout.addStretch(1)
        main.addWidget(assistant_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(34, 28, 34, 24)
        content_layout.setSpacing(14)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        self.hello = QLabel(f"Bonjour {settings.user_name}")
        self.hello.setObjectName("hello")
        subtitle = QLabel("Je m’occupe du compliqué. Tu choisis simplement quoi faire.")
        subtitle.setObjectName("muted")
        identity.addWidget(self.hello)
        identity.addWidget(subtitle)
        header.addLayout(identity)
        header.addStretch(1)
        self.status = QLabel("●  Jarvis démarre…")
        self.status.setObjectName("status")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignTop)
        content_layout.addLayout(header)

        toolbar = QHBoxLayout()
        brief = QPushButton("Fais-moi le point")
        brief.setObjectName("primaryButton")
        brief.clicked.connect(self.daily_brief)
        mail = QPushButton("Ouvrir mes mails")
        mail.clicked.connect(partial(self.start_app, "thunderbird"))
        files = QPushButton("Ouvrir mes documents")
        files.clicked.connect(partial(self.start_app, "explorer"))
        toolbar.addWidget(brief)
        toolbar.addWidget(mail)
        toolbar.addWidget(files)
        toolbar.addStretch(1)
        content_layout.addLayout(toolbar)

        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setObjectName("answer")
        self.answer.hide()
        content_layout.addWidget(self.answer)

        section = QLabel("À faire maintenant")
        section.setObjectName("sectionTitle")
        content_layout.addWidget(section)

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
            QMainWindow, QWidget { background: #ffffff; color: #172338; font-family: 'Segoe UI'; font-size: 16px; }
            #assistantPanel { background: #eef6ff; border-right: 1px solid #d7e3ef; }
            #hello { font-size: 36px; font-weight: 700; }
            #sectionTitle { font-size: 22px; font-weight: 700; margin-top: 4px; }
            #muted { color: #68778b; }
            #caption { background: rgba(255,255,255,0.94); border: 1px solid #d5e2ef; border-radius: 16px; padding: 13px; color: #35465d; font-size: 16px; }
            #status { color: #12643a; background: #edf8f1; border: 1px solid #caead5; border-radius: 15px; padding: 8px 12px; font-weight: 700; }
            #answer { background: #edf7ff; border: 1px solid #cce4f9; border-radius: 14px; padding: 12px 14px; color: #244765; }
            QPushButton { min-height: 48px; padding: 0 17px; border-radius: 12px; border: 1px solid #cbd7e4; background: #ffffff; color: #1d3552; font-weight: 650; }
            QPushButton:hover { background: #f5f8fc; border-color: #9eb7cf; }
            QPushButton:pressed { background: #eaf1f8; }
            #primaryButton { background: #1769bd; color: white; border-color: #1769bd; font-weight: 700; }
            #primaryButton:hover { background: #125ca7; }
            #linkButton { min-height: 40px; border: none; background: transparent; text-decoration: underline; color: #4f677e; }
            QFrame#taskCard { background: #ffffff; border: 1px solid #d6e0eb; border-radius: 16px; }
            QLabel#cardTitle { font-size: 20px; font-weight: 700; }
            QLabel#cardSummary { font-size: 17px; color: #34445b; }
            QLabel#recommendation { color: #244c70; font-weight: 600; }
            QLabel#deadline { color: #82530d; background: #fff4df; border-radius: 9px; padding: 5px 8px; font-weight: 650; }
            QListWidget { border: 1px solid #d6e0eb; border-radius: 12px; padding: 6px; font-size: 15px; }
            QListWidget::item { padding: 10px; }
            QListWidget::item:selected { background: #dcecff; color: #163b62; }
            #dialogTitle { font-size: 24px; font-weight: 700; }
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
        worker.signals.failed.connect(on_error or self.show_error)
        self.pool.start(worker)

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Jarvis", f"Je n’ai pas pu terminer cette action.\n\n{message}")

    def show_answer(self, text: str) -> None:
        self.answer.setText(text)
        self.answer.setVisible(bool(text.strip()))

    def refresh(self) -> None:
        self._worker(
            lambda: self.api.request("GET", "/api/actions"),
            self.render_cards,
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
        else:
            self.status.setText("●  Jarvis est prêt")

    def render_newsletters(self, payload: dict[str, object]) -> None:
        count = int(payload.get("count") or 0)
        suffix = "newsletter à ranger" if count == 1 else "newsletters à ranger"
        self.newsletter_label.setText(f"{count} {suffix}")

    def render_cards(self, cards: list[dict[str, object]]) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        visible = cards[:3]
        if not visible:
            empty = QLabel("Tout est calme. Je te préviendrai si quelque chose mérite ton attention.")
            empty.setWordWrap(True)
            empty.setObjectName("muted")
            empty.setStyleSheet("padding: 24px; border: 1px dashed #cbd7e5; border-radius: 14px;")
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
        layout.setContentsMargins(18, 16, 18, 16)
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
            label = QLabel(f"Je te conseille : {recommendation}")
            label.setObjectName("recommendation")
            label.setWordWrap(True)
            layout.addWidget(label)
        deadline = str(metadata.get("deadline_text") or "")
        if deadline:
            label = QLabel(f"Échéance : {deadline}")
            label.setObjectName("deadline")
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            layout.addWidget(label)
        actions = QHBoxLayout()
        options = card.get("options") if isinstance(card.get("options"), list) else []
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

    def daily_brief(self) -> None:
        self.show_answer("Je regarde ce qui mérite ton attention…")
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/assistant/ask",
                payload={
                    "text": (
                        "Fais-moi le point. Donne seulement les choses importantes, les échéances "
                        "et ce que je dois faire maintenant. Réponse très simple et courte."
                    ),
                    "speak": True,
                },
                timeout=30,
            ),
            lambda result: self.show_answer(str(result.get("answer") or "Rien d’urgent.")),
        )

    def start_app(self, name: str) -> None:
        self._worker(
            lambda: self.api.request("POST", "/api/desktop/start", payload={"app": name}),
            self._show_operation_result,
        )

    def _show_operation_result(self, result: dict[str, object]) -> None:
        detail = str(result.get("detail") or "")
        if detail:
            self.show_answer(detail)
        if not bool(result.get("ok", True)):
            self.show_error(detail or "L’action n’a pas abouti.")
        QTimer.singleShot(500, self.refresh)

    def handle_option(self, card: dict[str, object], option: dict[str, object]) -> None:
        card_id = str(card.get("id") or "")
        option_id = str(option.get("id") or "")
        kind = str(option.get("kind") or "")
        token = ""
        if bool(option.get("requires_confirmation")):
            token = self.authorize(
                "mail.prepare_reply",
                "Préparer un brouillon dans Thunderbird. Aucun mail ne sera envoyé.",
            ) or ""
            if not token:
                return
        payload = {"option_id": option_id}
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
            self.show_error(str(result.get("detail") or result.get("reason") or "Action bloquée."))
            return
        if kind == "search_files":
            items = result.get("results") if isinstance(result.get("results"), list) else []
            if not items:
                self.show_answer("Je n’ai pas trouvé de document correspondant.")
                return
            self.choose_file(card, items)
            return
        self._show_operation_result(result)

    def choose_file(self, card: dict[str, object], results: list[dict[str, object]]) -> None:
        dialog = FileChoiceDialog(results, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_path:
            return
        if dialog.mode == "open":
            self._worker(
                lambda: self.api.request(
                    "POST", "/api/files/open", payload={"path": dialog.selected_path}
                ),
                self._show_operation_result,
            )
            return
        if dialog.mode == "attach":
            token = self.authorize(
                "mail.prepare_reply_attachment",
                f"Préparer un brouillon avec le document « {Path(dialog.selected_path).name} ». ",
            )
            if not token:
                return
            card_id = str(card.get("id") or "")
            self._worker(
                lambda: self.api.request(
                    "POST",
                    f"/api/actions/{card_id}/attach",
                    payload={
                        "paths": [dialog.selected_path],
                        "authorization_token": token,
                    },
                    timeout=30,
                ),
                self._show_operation_result,
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
        self._worker(
            lambda: self.api.request(
                "POST",
                f"/api/actions/{card_id}/snooze",
                payload={"hours": 4, "authorization_token": token},
            ),
            self._show_operation_result,
        )

    def sort_newsletters(self) -> None:
        token = self.authorize(
            "mail.sort_newsletters",
            "Déplacer les newsletters détectées dans le dossier Newsletters de Thunderbird.",
        )
        if not token:
            return
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/newsletters/sort",
                payload={"authorization_token": token},
            ),
            self._show_operation_result,
        )

    def authorize(self, action_key: str, description: str) -> str | None:
        first = QMessageBox.question(
            self,
            "Autorisation 1 sur 2",
            f"Première vérification\n\n{description}\n\nVeux-tu continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if first != QMessageBox.StandardButton.Yes:
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
            self.show_error(str(exc))
            return None

        second = QMessageBox.question(
            self,
            "Autorisation 2 sur 2",
            f"Dernière vérification\n\n{description}\n\nConfirmes-tu une seconde fois ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if second != QMessageBox.StandardButton.Yes:
            return None
        try:
            step_two = self.api.request(
                "POST", f"/api/confirmations/{challenge_id}/confirm", payload={}, timeout=4
            )
        except Exception as exc:
            self.show_error(str(exc))
            return None
        token = step_two.get("authorization_token")
        if not bool(step_two.get("completed")) or not isinstance(token, str) or not token:
            self.show_error("La double autorisation n’a pas été validée.")
            return None
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
        self.caption.setText("Je suis prête.")


def run() -> None:
    """Start Jarvis as a real native Windows application, with localhost API hidden behind it."""

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setOrganizationName("Jarvis Papa")
    app.setFont(QFont("Segoe UI", 10))

    # QLockFile is imported lazily to keep the module straightforward for PyInstaller.
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

    window = MainWindow()
    window.show()
    exit_code = app.exec()
    backend.stop()
    lock.unlock()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    run()
