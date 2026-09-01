from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.files import is_allowed_document, is_allowed_path


@dataclass(frozen=True, slots=True)
class WindowsSkillResult:
    ok: bool
    state: str
    skill: str
    detail: str
    target: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class WindowsSkills:
    """Small, deterministic Windows skills built above semantic OS APIs/UIA.

    These helpers never use pixel coordinates. Mutating skills are deliberately
    separate from the LLM tool registry and must be called behind the server
    confirmation policy.
    """

    @property
    def available(self) -> bool:
        return platform.system() == "Windows"

    def reveal_path(self, raw_path: str) -> WindowsSkillResult:
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            return WindowsSkillResult(False, "failed", "reveal_path", "Chemin invalide.", raw_path)
        if not path.exists():
            return WindowsSkillResult(False, "failed", "reveal_path", "Fichier ou dossier introuvable.", str(path))
        allowed = is_allowed_path(path) if path.is_dir() else is_allowed_document(path)
        if not allowed:
            return WindowsSkillResult(
                False,
                "failed",
                "reveal_path",
                "Jarvis refuse ce chemin car il sort des emplacements autorisés.",
                str(path),
            )
        if not self.available:
            return WindowsSkillResult(False, "failed", "reveal_path", "Disponible uniquement sur Windows.", str(path))
        try:
            if path.is_dir():
                subprocess.Popen(
                    ["explorer.exe", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                subprocess.Popen(
                    ["explorer.exe", "/select,", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except OSError as exc:
            return WindowsSkillResult(False, "failed", "reveal_path", f"Explorateur indisponible : {exc}", str(path))
        return WindowsSkillResult(True, "success", "reveal_path", "Le document est affiché dans l'Explorateur Windows.", str(path))

    def choose_file_in_dialog(self, window_title: str, raw_path: str) -> WindowsSkillResult:
        """Fill the standard Windows file picker using stable UIA automation IDs."""
        if not self.available:
            return WindowsSkillResult(False, "failed", "choose_file_dialog", "Disponible uniquement sur Windows.")
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            return WindowsSkillResult(False, "failed", "choose_file_dialog", "Chemin invalide.", raw_path)
        if not path.is_file() or not is_allowed_document(path):
            return WindowsSkillResult(
                False,
                "failed",
                "choose_file_dialog",
                "Le fichier n'est pas un document local autorisé.",
                str(path),
            )
        try:
            from pywinauto import Desktop

            matches = [
                window
                for window in Desktop(backend="uia").windows()
                if window_title.casefold() in window.window_text().casefold()
            ]
            if len(matches) != 1:
                return WindowsSkillResult(
                    False,
                    "failed",
                    "choose_file_dialog",
                    "La boîte de dialogue est absente ou ambiguë ; Jarvis refuse de choisir au hasard.",
                    str(path),
                )
            dialog = matches[0]
            dialog.wait("exists ready", timeout=5)
            filename_edit = dialog.child_window(auto_id="1148", control_type="Edit")
            open_button = dialog.child_window(auto_id="1", control_type="Button")
            if not filename_edit.exists(timeout=2) or not open_button.exists(timeout=2):
                return WindowsSkillResult(
                    False,
                    "failed",
                    "choose_file_dialog",
                    "Cette boîte de dialogue ne fournit pas les contrôles Windows standards vérifiables.",
                    str(path),
                )
            filename_edit.set_edit_text(str(path))
            if filename_edit.window_text().strip() != str(path):
                return WindowsSkillResult(
                    False,
                    "failed",
                    "choose_file_dialog",
                    "Le chemin saisi n'a pas pu être vérifié.",
                    str(path),
                )
            open_button.invoke()
            time.sleep(0.25)
            still_open = dialog.exists(timeout=0.2)
        except Exception as exc:  # noqa: BLE001 - COM/UIA exposes heterogeneous exceptions.
            return WindowsSkillResult(False, "failed", "choose_file_dialog", f"Sélection impossible : {type(exc).__name__}.", str(path))
        return WindowsSkillResult(
            True,
            "partial" if still_open else "success",
            "choose_file_dialog",
            (
                "Le fichier a été sélectionné, mais la boîte de dialogue est encore ouverte."
                if still_open
                else "Windows a accepté le fichier sélectionné."
            ),
            str(path),
        )

    def print_document(self, raw_path: str) -> WindowsSkillResult:
        """Submit an allowed document to the registered Windows print verb.

        Submission is intentionally PARTIAL: the OS accepting the print verb is
        not proof that paper physically came out of a printer.
        """
        if not self.available:
            return WindowsSkillResult(False, "failed", "print_document", "Disponible uniquement sur Windows.")
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError:
            return WindowsSkillResult(False, "failed", "print_document", "Chemin invalide.", raw_path)
        if not path.is_file() or not is_allowed_document(path):
            return WindowsSkillResult(False, "failed", "print_document", "Document non autorisé.", str(path))
        try:
            os.startfile(str(path), "print")  # type: ignore[attr-defined]
        except OSError as exc:
            return WindowsSkillResult(False, "failed", "print_document", f"Impression refusée par Windows : {exc}", str(path))
        return WindowsSkillResult(
            True,
            "partial",
            "print_document",
            "Windows a accepté la demande d'impression. Jarvis ne prétend pas que la page est sortie sans confirmation supplémentaire.",
            str(path),
        )

    def open_windows_settings(self, page: str = "printers") -> WindowsSkillResult:
        if not self.available:
            return WindowsSkillResult(False, "failed", "open_settings", "Disponible uniquement sur Windows.")
        allowed = {
            "printers": "ms-settings:printers",
            "bluetooth": "ms-settings:bluetooth",
            "network": "ms-settings:network-status",
            "sound": "ms-settings:sound",
            "display": "ms-settings:display",
        }
        uri = allowed.get(page.casefold())
        if not uri:
            return WindowsSkillResult(False, "failed", "open_settings", "Page de paramètres non autorisée.", page)
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
        except OSError as exc:
            return WindowsSkillResult(False, "failed", "open_settings", f"Paramètres Windows indisponibles : {exc}", page)
        return WindowsSkillResult(True, "success", "open_settings", "La page des paramètres Windows est ouverte.", page)


windows_skills = WindowsSkills()
