import os
import platform
import shutil
import subprocess
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote_plus


@dataclass(frozen=True, slots=True)
class DesktopResult:
    ok: bool
    action: str
    target: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DesktopController:
    APP_ALIASES = {
        "thunderbird": ("thunderbird.exe", "thunderbird"),
        "explorer": ("explorer.exe",),
        "notepad": ("notepad.exe",),
        "calculator": ("calc.exe",),
    }

    @property
    def is_windows(self) -> bool:
        return platform.system() == "Windows"

    def open_path(self, raw_path: str) -> DesktopResult:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            return DesktopResult(False, "open_path", str(path), "Fichier ou dossier introuvable.")
        if not self.is_windows:
            return DesktopResult(False, "open_path", str(path), "Action disponible sur Windows.")
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            return DesktopResult(False, "open_path", str(path), str(exc))
        return DesktopResult(True, "open_path", str(path), "Ouverture demandée à Windows.")

    def start_app(self, alias: str) -> DesktopResult:
        normalized = alias.strip().lower()
        candidates = self.APP_ALIASES.get(normalized)
        if not candidates:
            return DesktopResult(False, "start_app", alias, "Application non autorisée.")

        executable = next((shutil.which(item) for item in candidates if shutil.which(item)), None)
        if not executable and self.is_windows and normalized == "explorer":
            executable = "explorer.exe"
        if not executable:
            return DesktopResult(False, "start_app", alias, "Application introuvable.")

        try:
            subprocess.Popen(
                [executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return DesktopResult(False, "start_app", alias, str(exc))
        return DesktopResult(True, "start_app", alias, "Application lancée.")

    def search_web(self, query: str) -> DesktopResult:
        query = query.strip()
        if not query:
            return DesktopResult(False, "web_search", query, "Recherche vide.")
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        opened = webbrowser.open(url, new=2)
        return DesktopResult(bool(opened), "web_search", query, "Recherche ouverte dans le navigateur.")


desktop_controller = DesktopController()
