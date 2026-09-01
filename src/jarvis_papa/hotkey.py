from __future__ import annotations

import sys
import threading
from collections.abc import Callable


class GlobalHotkeyService:
    """Windows Ctrl+Alt+J hotkey using RegisterHotKey, with graceful fallback."""

    HOTKEY_ID = 0x4A50
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._callback: Callable[[], None] | None = None
        self._thread_id: int | None = None
        self._registered = False

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    @property
    def registered(self) -> bool:
        return self._registered

    def start(self, callback: Callable[[], None]) -> bool:
        if not self.available or self._thread is not None:
            return False
        self._callback = callback
        ready = threading.Event()

        def worker() -> None:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = int(kernel32.GetCurrentThreadId())
            ok = bool(
                user32.RegisterHotKey(
                    None,
                    self.HOTKEY_ID,
                    self.MOD_CONTROL | self.MOD_ALT,
                    ord("J"),
                )
            )
            self._registered = ok
            ready.set()
            if not ok:
                return
            message = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                    if message.message == self.WM_HOTKEY and int(message.wParam) == self.HOTKEY_ID:
                        callback_fn = self._callback
                        if callback_fn is not None:
                            try:
                                callback_fn()
                            except Exception:
                                continue
            finally:
                user32.UnregisterHotKey(None, self.HOTKEY_ID)
                self._registered = False

        self._thread = threading.Thread(target=worker, name="JarvisGlobalHotkey", daemon=True)
        self._thread.start()
        ready.wait(timeout=1.5)
        return self._registered

    def stop(self) -> None:
        if not self.available or self._thread_id is None:
            return
        try:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
        except (AttributeError, OSError):
            return
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        self._callback = None


global_hotkey = GlobalHotkeyService()
