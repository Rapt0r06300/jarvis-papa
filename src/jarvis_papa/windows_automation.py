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
    """Semantic Windows automation through UI Automation, never blind coordinates."""

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
            window = self._unique_window(title)
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
            window = self._unique_window(title)
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
            window = self._unique_window(window_title)
            control = self._unique_control(window, control_name, control_type)
            if not hasattr(control, "invoke"):
                return UIAResult(
                    False,
                    "invoke_control",
                    "Ce contrôle ne fournit pas une action UI Automation sûre. Jarvis refuse le clic aveugle.",
                )
            control.invoke()
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "invoke_control", str(exc))
        return UIAResult(True, "invoke_control", "Contrôle UI Automation activé.")

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
            window = self._unique_window(window_title)
            control = self._unique_control(window, control_name, "Edit")
            if not hasattr(control, "set_edit_text"):
                return UIAResult(
                    False,
                    "set_text",
                    "Ce champ ne permet pas une saisie UI Automation vérifiable. Jarvis n'utilise pas de frappe aveugle.",
                )
            control.set_edit_text(text)
            actual = control.window_text()
            if actual != text:
                return UIAResult(
                    False,
                    "set_text",
                    "La saisie n'a pas pu être vérifiée ; Jarvis la considère comme échouée.",
                )
        except Exception as exc:  # noqa: BLE001 - pywinauto wraps multiple COM/UIA errors.
            return UIAResult(False, "set_text", str(exc))
        return UIAResult(True, "set_text", "Texte saisi et vérifié dans le contrôle.")

    @staticmethod
    def _unique_window(title: str):
        from pywinauto import Desktop

        pattern = re.compile(f".*{re.escape(title.strip())}.*", re.IGNORECASE)
        matches = [
            window
            for window in Desktop(backend="uia").windows()
            if pattern.fullmatch(window.window_text().strip())
        ]
        if not matches:
            raise LookupError("Fenêtre Windows introuvable.")
        if len(matches) > 1:
            raise LookupError("Plusieurs fenêtres correspondent. Jarvis refuse de choisir au hasard.")
        matches[0].wait("exists ready", timeout=5)
        return matches[0]

    @staticmethod
    def _unique_control(window, control_name: str, control_type: str | None = None):
        expected = control_name.strip().casefold()
        matches = []
        for control in window.descendants():
            if control.window_text().strip().casefold() != expected:
                continue
            actual_type = str(control.element_info.control_type or "")
            if control_type and actual_type.casefold() != control_type.casefold():
                continue
            matches.append(control)
        if not matches:
            raise LookupError("Contrôle Windows introuvable.")
        if len(matches) > 1:
            raise LookupError("Plusieurs contrôles correspondent. Jarvis refuse de choisir au hasard.")
        return matches[0]


windows_uia = WindowsUIAutomation()
