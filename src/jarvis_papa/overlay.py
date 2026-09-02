from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class JarvisOverlay(QDialog):
    """Small native companion surface for the canonical Jarvis desktop."""

    def __init__(
        self,
        parent: QWidget,
        *,
        on_query: Callable[[str], None],
        on_mail: Callable[[], None],
        on_documents: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_query = on_query
        self._on_mail = on_mail
        self._on_documents = on_documents
        self._on_stop = on_stop
        self.setWindowTitle("Jarvis")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumWidth(520)
        self.setMaximumWidth(680)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Jarvis est là")
        title.setStyleSheet("font-size: 20px; font-weight: 650;")
        root.addWidget(title)

        subtitle = QLabel("Demande quelque chose, ou choisis une action simple.")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Demandez quelque chose à Jarvis…")
        self.input.setMinimumHeight(46)
        self.input.returnPressed.connect(self._submit)
        root.addWidget(self.input)

        row = QHBoxLayout()
        ask = QPushButton("Demander")
        ask.setMinimumHeight(42)
        ask.clicked.connect(self._submit)
        row.addWidget(ask)

        mail = QPushButton("Mails")
        mail.setMinimumHeight(42)
        mail.clicked.connect(self._mail)
        row.addWidget(mail)

        documents = QPushButton("Documents")
        documents.setMinimumHeight(42)
        documents.clicked.connect(self._documents)
        row.addWidget(documents)

        stop = QPushButton("Arrêter Jarvis")
        stop.setMinimumHeight(42)
        stop.clicked.connect(self._stop)
        row.addWidget(stop)
        root.addLayout(row)

        hint = QLabel("Raccourci : Ctrl + Alt + J   •   Échap pour masquer")
        hint.setStyleSheet("font-size: 11px;")
        root.addWidget(hint)

        QShortcut(QKeySequence("Escape"), self, activated=self.hide)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def _submit(self) -> None:
        text = " ".join(self.input.text().split()).strip()
        if not text:
            return
        self.input.clear()
        self.hide()
        self._on_query(text)

    def _mail(self) -> None:
        self.hide()
        self._on_mail()

    def _documents(self) -> None:
        self.hide()
        self._on_documents()

    def _stop(self) -> None:
        self.hide()
        self._on_stop()


class GlobalOverlayHotkey:
    """Toggle the overlay from any Windows app using Ctrl+Alt+J.

    RegisterHotKey is preferred. A lightweight key-state fallback is used only
    if another application already owns that combination.
    """

    HOTKEY_ID = 0x4A50
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    VK_J = 0x4A

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self._registered = False
        self._last_down = False
        self._timer = QTimer()
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._poll)
        if sys.platform == "win32":
            try:
                self._registered = bool(
                    ctypes.windll.user32.RegisterHotKey(
                        None,
                        self.HOTKEY_ID,
                        self.MOD_CONTROL | self.MOD_ALT,
                        self.VK_J,
                    )
                )
            except (AttributeError, OSError):
                self._registered = False
        # Qt does not expose thread WM_HOTKEY without a native filter here;
        # polling remains deterministic and is also the conflict fallback.
        self._timer.start()

    def close(self) -> None:
        self._timer.stop()
        if self._registered and sys.platform == "win32":
            try:
                ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)
            except (AttributeError, OSError):
                pass
        self._registered = False

    def _poll(self) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
            j_key = bool(user32.GetAsyncKeyState(self.VK_J) & 0x8000)
        except (AttributeError, OSError):
            return
        down = ctrl and alt and j_key
        if down and not self._last_down:
            self.callback()
        self._last_down = down
