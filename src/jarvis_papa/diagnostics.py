from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from jarvis_papa.ai import local_ai
from jarvis_papa.browser import browser_agent
from jarvis_papa.config import settings
from jarvis_papa.files import file_searcher
from jarvis_papa.thunderbird import thunderbird_bridge_state, thunderbird_commands
from jarvis_papa.voice import voice_service


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    id: str
    label: str
    status: str
    detail: str
    remediation: str = ""
    data: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class JarvisDiagnostics:
    """Read-only self-checks for the local Windows secretary stack."""

    def run(self) -> dict[str, object]:
        started = time.monotonic()
        checks = [
            self._check_local_security(),
            self._check_runtime_storage(),
            self._check_files(),
            self._check_browser(),
            self._check_ai(),
            self._check_voice(),
            self._check_windows_environment(),
            self._check_thunderbird_installation(),
            self._check_native_manifest(),
            self._check_native_registry(),
            self._check_thunderbird_bridge(),
            self._check_thunderbird_commands(),
        ]
        errors = [item for item in checks if item.status == "error"]
        warnings = [item for item in checks if item.status == "warning"]
        status = "error" if errors else ("degraded" if warnings else "ok")
        score = max(0, 100 - 20 * len(errors) - 5 * len(warnings))
        return {
            "status": status,
            "ready": not errors,
            "score": score,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "errors": len(errors),
            "warnings": len(warnings),
            "checks": [item.to_dict() for item in checks],
        }

    @staticmethod
    def _check_local_security() -> DiagnosticCheck:
        allowed = settings.host in {"127.0.0.1", "localhost", "::1"}
        return DiagnosticCheck(
            id="local_security",
            label="Protection locale",
            status="ok" if allowed else "error",
            detail=(
                "Jarvis écoute uniquement sur l'ordinateur."
                if allowed
                else f"Jarvis est configuré sur l'hôte {settings.host!r}, qui n'est pas local."
            ),
            remediation=(
                ""
                if allowed
                else "Remets JARVIS_HOST=127.0.0.1 dans .env avant de relancer Jarvis."
            ),
        )

    @staticmethod
    def _check_runtime_storage() -> DiagnosticCheck:
        runtime = settings.runtime_dir.resolve()
        marker = runtime / f".diagnostic-{uuid4().hex}.tmp"
        try:
            runtime.mkdir(parents=True, exist_ok=True)
            marker.write_text("jarvis", encoding="utf-8")
            marker.unlink()
        except OSError as exc:
            return DiagnosticCheck(
                id="runtime_storage",
                label="Stockage local",
                status="error",
                detail=f"Jarvis ne peut pas écrire dans son dossier runtime : {type(exc).__name__}.",
                remediation="Vérifie les droits du dossier Jarvis et l'espace disque.",
                data={"path": str(runtime)},
            )
        return DiagnosticCheck(
            id="runtime_storage",
            label="Stockage local",
            status="ok",
            detail="Le stockage local de Jarvis est accessible en lecture et écriture.",
            data={"path": str(runtime)},
        )

    @staticmethod
    def _check_files() -> DiagnosticCheck:
        roots = [Path(item).expanduser() for item in settings.file_search_roots]
        existing = [str(item.resolve()) for item in roots if item.exists() and item.is_dir()]
        if not existing:
            return DiagnosticCheck(
                id="file_search",
                label="Recherche de documents",
                status="warning",
                detail="Aucun dossier de recherche configuré n'est actuellement accessible.",
                remediation="Vérifie Documents, Bureau et Téléchargements dans la configuration.",
                data={"backend": file_searcher.backend},
            )
        return DiagnosticCheck(
            id="file_search",
            label="Recherche de documents",
            status="ok",
            detail=f"Recherche prête via {file_searcher.backend} sur {len(existing)} dossier(s).",
            data={"backend": file_searcher.backend, "roots": existing},
        )

    @staticmethod
    def _check_browser() -> DiagnosticCheck:
        if browser_agent.available:
            return DiagnosticCheck(
                id="browser",
                label="Navigateur automatisé",
                status="ok",
                detail="Playwright et Chromium sont disponibles pour les recherches web contrôlées.",
            )
        return DiagnosticCheck(
            id="browser",
            label="Navigateur automatisé",
            status="warning",
            detail="Playwright est installé mais Chromium n'est pas utilisable.",
            remediation="Relance INSTALLER_JARVIS.bat ou python -m playwright install chromium.",
        )

    @staticmethod
    def _check_ai() -> DiagnosticCheck:
        state = local_ai.status()
        if not state.get("enabled"):
            return DiagnosticCheck(
                id="local_ai",
                label="IA locale",
                status="info",
                detail="L'IA locale est désactivée ; le mode secrétaire déterministe reste disponible.",
            )
        if state.get("available") and state.get("model_installed") is not False:
            return DiagnosticCheck(
                id="local_ai",
                label="IA locale",
                status="ok",
                detail=f"Ollama répond et le modèle {state.get('model')} est disponible.",
                data={"provider": state.get("provider"), "model": state.get("model")},
            )
        return DiagnosticCheck(
            id="local_ai",
            label="IA locale",
            status="warning",
            detail="Ollama ou le modèle local n'est pas prêt ; Jarvis utilisera son mode de secours.",
            remediation="Lance INSTALLER_IA_LOCALE.bat si tu veux réactiver l'IA locale.",
            data={"provider": state.get("provider"), "model": state.get("model")},
        )

    @staticmethod
    def _check_voice() -> DiagnosticCheck:
        state = voice_service.status()
        providers = state.get("providers")
        available: list[str] = []
        if isinstance(providers, dict):
            for name, value in providers.items():
                if isinstance(value, dict) and value.get("available"):
                    available.append(str(name))
        if not settings.speech_enabled:
            return DiagnosticCheck(
                id="voice",
                label="Voix de Jarvis",
                status="info",
                detail="La synthèse vocale est volontairement désactivée.",
            )
        if available:
            return DiagnosticCheck(
                id="voice",
                label="Voix de Jarvis",
                status="ok",
                detail=f"Au moins une voix est prête : {', '.join(available)}.",
                data={"available_providers": available},
            )
        return DiagnosticCheck(
            id="voice",
            label="Voix de Jarvis",
            status="warning",
            detail="Aucun moteur vocal n'est actuellement disponible.",
            remediation="Sur Windows, relance INSTALLER_VOIX_LOCALE.bat ou vérifie la voix système.",
        )

    @staticmethod
    def _check_windows_environment() -> DiagnosticCheck:
        if sys.platform != "win32":
            return DiagnosticCheck(
                id="windows_environment",
                label="Environnement Windows",
                status="info",
                detail="Ce diagnostic n'est pas exécuté sur Windows ; les contrôles natifs sont ignorés ici.",
            )
        return DiagnosticCheck(
            id="windows_environment",
            label="Environnement Windows",
            status="ok",
            detail="Jarvis s'exécute sous Windows ; les contrôles natifs peuvent être vérifiés.",
        )

    @classmethod
    def _check_thunderbird_installation(cls) -> DiagnosticCheck:
        if sys.platform != "win32":
            return cls._windows_only_info("thunderbird_install", "Thunderbird")
        executable = cls._find_thunderbird()
        if executable:
            return DiagnosticCheck(
                id="thunderbird_install",
                label="Thunderbird",
                status="ok",
                detail="Thunderbird est installé et détectable.",
                data={"path": str(executable)},
            )
        return DiagnosticCheck(
            id="thunderbird_install",
            label="Thunderbird",
            status="warning",
            detail="Thunderbird n'a pas été trouvé dans les emplacements Windows habituels.",
            remediation="Installe Thunderbird ou vérifie son chemin d'installation.",
        )

    @classmethod
    def _check_native_manifest(cls) -> DiagnosticCheck:
        if sys.platform != "win32":
            return cls._windows_only_info("native_manifest", "Pont Thunderbird")
        path = cls._native_manifest_path()
        if path is None or not path.is_file():
            return DiagnosticCheck(
                id="native_manifest",
                label="Pont Thunderbird",
                status="warning",
                detail="Le manifeste Native Messaging de Jarvis est absent.",
                remediation="Relance scripts\\INSTALLER_PONT_THUNDERBIRD.ps1.",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return DiagnosticCheck(
                id="native_manifest",
                label="Pont Thunderbird",
                status="warning",
                detail="Le manifeste Native Messaging existe mais n'est pas lisible.",
                remediation="Relance scripts\\INSTALLER_PONT_THUNDERBIRD.ps1.",
                data={"path": str(path)},
            )
        host_path = Path(str(payload.get("path") or "")).expanduser()
        allowed = payload.get("allowed_extensions")
        valid = (
            payload.get("name") == settings.thunderbird_native_host_name
            and payload.get("type") == "stdio"
            and isinstance(allowed, list)
            and "jarvis-papa@local" in allowed
            and host_path.is_file()
        )
        if not valid:
            return DiagnosticCheck(
                id="native_manifest",
                label="Pont Thunderbird",
                status="warning",
                detail="Le manifeste Native Messaging existe mais sa configuration n'est pas complète.",
                remediation="Relance scripts\\INSTALLER_PONT_THUNDERBIRD.ps1.",
                data={"path": str(path)},
            )
        return DiagnosticCheck(
            id="native_manifest",
            label="Pont Thunderbird",
            status="ok",
            detail="Le manifeste Native Messaging et l'exécutable Jarvis sont cohérents.",
            data={"manifest": str(path), "host": str(host_path)},
        )

    @classmethod
    def _check_native_registry(cls) -> DiagnosticCheck:
        if sys.platform != "win32":
            return cls._windows_only_info("native_registry", "Registre Thunderbird")
        path = cls._native_manifest_path()
        try:
            import winreg

            key_name = (
                rf"Software\Mozilla\NativeMessagingHosts\{settings.thunderbird_native_host_name}"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
                value, _ = winreg.QueryValueEx(key, None)
        except (ImportError, OSError):
            return DiagnosticCheck(
                id="native_registry",
                label="Registre Thunderbird",
                status="warning",
                detail="La clé Windows du pont Native Messaging est absente ou inaccessible.",
                remediation="Relance scripts\\INSTALLER_PONT_THUNDERBIRD.ps1.",
            )
        try:
            registry_path = Path(str(value)).resolve()
            expected = path.resolve() if path else None
        except OSError:
            registry_path = Path(str(value))
            expected = path
        if expected is None or registry_path != expected:
            return DiagnosticCheck(
                id="native_registry",
                label="Registre Thunderbird",
                status="warning",
                detail="La clé Windows Native Messaging ne pointe pas vers le manifeste attendu.",
                remediation="Relance scripts\\INSTALLER_PONT_THUNDERBIRD.ps1.",
                data={"value": str(value)},
            )
        return DiagnosticCheck(
            id="native_registry",
            label="Registre Thunderbird",
            status="ok",
            detail="La clé Windows Native Messaging pointe vers le bon manifeste.",
        )

    @staticmethod
    def _check_thunderbird_bridge() -> DiagnosticCheck:
        state = thunderbird_bridge_state.snapshot()
        if state.get("connected"):
            return DiagnosticCheck(
                id="thunderbird_bridge",
                label="Connexion Thunderbird ↔ Jarvis",
                status="ok",
                detail="Le pont Thunderbird a envoyé un signal de vie récemment.",
                data=state,
            )
        status = "info" if sys.platform != "win32" else "warning"
        return DiagnosticCheck(
            id="thunderbird_bridge",
            label="Connexion Thunderbird ↔ Jarvis",
            status=status,
            detail="Aucun signal de vie récent du pont Thunderbird.",
            remediation=(
                "Ouvre Thunderbird et vérifie que l'extension Jarvis Papa est activée."
                if sys.platform == "win32"
                else ""
            ),
            data=state,
        )

    @staticmethod
    def _check_thunderbird_commands() -> DiagnosticCheck:
        summary = thunderbird_commands.summary()
        if summary["failed"]:
            return DiagnosticCheck(
                id="thunderbird_commands",
                label="Commandes Thunderbird",
                status="warning",
                detail=f"{summary['failed']} commande(s) Thunderbird ont échoué récemment.",
                remediation="Consulte les erreurs récentes avant de relancer une action.",
                data=summary,
            )
        return DiagnosticCheck(
            id="thunderbird_commands",
            label="Commandes Thunderbird",
            status="ok",
            detail=f"Aucune commande Thunderbird en échec. {summary['pending']} en attente.",
            data=summary,
        )

    @staticmethod
    def _windows_only_info(check_id: str, label: str) -> DiagnosticCheck:
        return DiagnosticCheck(
            id=check_id,
            label=label,
            status="info",
            detail="Contrôle Windows non applicable sur ce système.",
        )

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _native_manifest_path(cls) -> Path | None:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return (
            Path(appdata)
            / "Mozilla"
            / "NativeMessagingHosts"
            / f"{settings.thunderbird_native_host_name}.json"
        )

    @staticmethod
    def _find_thunderbird() -> Path | None:
        direct = shutil.which("thunderbird.exe")
        if direct:
            return Path(direct)
        candidates: list[Path] = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "Mozilla Thunderbird" / "thunderbird.exe")
        return next((item for item in candidates if item.is_file()), None)


diagnostics = JarvisDiagnostics()


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Diagnostic complet de Jarvis Papa")
    parser.add_argument("--json", action="store_true", help="Afficher le rapport en JSON")
    args = parser.parse_args()
    report = diagnostics.run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Jarvis Papa — diagnostic : {str(report['status']).upper()} ({report['score']}/100)")
        for item in report["checks"]:
            if not isinstance(item, dict):
                continue
            marker = {"ok": "OK", "warning": "ATTENTION", "error": "ERREUR", "info": "INFO"}.get(
                str(item.get("status")), "INFO"
            )
            print(f"[{marker}] {item.get('label')}: {item.get('detail')}")
            remediation = str(item.get("remediation") or "")
            if remediation:
                print(f"         -> {remediation}")
    raise SystemExit(0 if report["ready"] else 2)


if __name__ == "__main__":
    run_cli()
