import importlib.util
import platform
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class UIAResult:
    ok: bool
    action: str
    detail: str
    data: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class WindowsUIAutomation:
    """Semantic Windows automation through the Microsoft UI Automation backend."""

    @property
    def available(self) -> bool:
        return platform.system() == "Windows" and importlib.util.find_spec("pywinauto") is not None

    def list_windows(self, limit: int = 40) -> UIAResult:
        if not self.available:
            return UIAResult(False, "list_windows", "UI Automation n'est pas disponible sur ce système.")
        try:
            from pywinauto import Desktop

            windows = Desktop(backend="uia").windows()
            data = []
            for window in windows[:limit]:
                title = window.window_text().strip()
                if title:
                    data.append(
                        {
                            "title": title[:250],
                            "control_type": str(window.element_info.control_type or "Window"),
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "list_windows", str(exc))
        return UIAResult(True, "list_windows", "Fenêtres détectées.", tuple(data))

    def inspect_window(self, title: str, limit: int = 100) -> UIAResult:
        if not self.available:
            return UIAResult(False, "inspect_window", "UI Automation n'est pas disponible sur ce système.")
        try:
            from pywinauto import Desktop

            window = Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")
            window.wait("exists ready", timeout=5)
            data = []
            for control in window.descendants()[:limit]:
                name = control.window_text().strip()
                info = control.element_info
                if name or info.automation_id:
                    data.append(
                        {
                            "name": name[:250],
                            "control_type": str(info.control_type or ""),
                            "automation_id": str(info.automation_id or ""),
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "inspect_window", str(exc))
        return UIAResult(True, "inspect_window", "Contrôles UI détectés.", tuple(data))

    def focus_window(self, title: str) -> UIAResult:
        if not self.available:
            return UIAResult(False, "focus_window", "UI Automation n'est pas disponible sur ce système.")
        try:
            from pywinauto import Desktop

            window = Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")
            window.wait("exists ready", timeout=5)
            window.set_focus()
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "focus_window", str(exc))
        return UIAResult(True, "focus_window", "Fenêtre activée.")

    def invoke_control(
        self,
        *,
        window_title: str,
        control_name: str,
        control_type: str | None = None,
    ) -> UIAResult:
        if not self.available:
            return UIAResult(False, "invoke_control", "UI Automation n'est pas disponible sur ce système.")
        try:
            from pywinauto import Desktop

            window = Desktop(backend="uia").window(title_re=f".*{re.escape(window_title)}.*")
            window.wait("exists ready", timeout=5)
            kwargs: dict[str, str] = {"title": control_name}
            if control_type:
                kwargs["control_type"] = control_type
            control = window.child_window(**kwargs).wrapper_object()
            if hasattr(control, "invoke"):
                control.invoke()
            else:
                control.click_input()
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "invoke_control", str(exc))
        return UIAResult(True, "invoke_control", "Contrôle activé.")

    def set_text(
        self,
        *,
        window_title: str,
        control_name: str,
        text: str,
    ) -> UIAResult:
        if not self.available:
            return UIAResult(False, "set_text", "UI Automation n'est pas disponible sur ce système.")
        try:
            from pywinauto import Desktop

            window = Desktop(backend="uia").window(title_re=f".*{re.escape(window_title)}.*")
            window.wait("exists ready", timeout=5)
            control = window.child_window(title=control_name).wrapper_object()
            if hasattr(control, "set_edit_text"):
                control.set_edit_text(text)
            else:
                control.set_focus()
                control.type_keys(text, with_spaces=True, set_foreground=False)
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "set_text", str(exc))
        return UIAResult(True, "set_text", "Texte saisi dans le contrôle.")


windows_uia = WindowsUIAutomation()
