import os
import sys
from pathlib import Path

import pytest


def test_desktop_ui_does_not_embed_or_launch_a_browser() -> None:
    source = (Path(__file__).parents[1] / "src" / "jarvis_papa" / "desktop_app.py").read_text(
        encoding="utf-8"
    )
    forbidden = ("QWebEngine", "QWebView", "webbrowser.open", "Start-Process http")
    assert all(token not in source for token in forbidden)
    assert "QMainWindow" in source
    assert "AvatarWidget" in source


@pytest.mark.skipif(sys.platform != "win32", reason="L'interface native cible Windows")
def test_native_window_can_be_constructed_offscreen() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from jarvis_papa.desktop_app import AvatarWidget, MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    avatars = window.findChildren(AvatarWidget)

    assert app is not None
    assert window.windowTitle() == "Jarvis"
    assert len(avatars) == 1
    window.close()
