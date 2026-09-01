from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.ai import local_ai
from jarvis_papa.config import settings
from jarvis_papa.diagnostics import diagnostics
from jarvis_papa.voice import voice_service


@dataclass(frozen=True, slots=True)
class RepairResult:
    component: str
    state: str
    detail: str
    retry_count: int = 0

    @property
    def ok(self) -> bool:
        return self.state == "success"

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"ok": self.ok}


class RepairService:
    """Bounded self-repair with cooldown and no infinite restart loops."""

    MAX_ATTEMPTS = 2
    WINDOW_SECONDS = 600.0
    CIRCUIT_SECONDS = 300.0

    def __init__(self) -> None:
        self.state_path = settings.runtime_dir / "repair_state.json"

    def plan(self) -> dict[str, object]:
        report = diagnostics.run()
        suggestions: list[dict[str, str]] = []
        for check in report.get("checks", []):
            if not isinstance(check, dict) or check.get("status") not in {"warning", "error"}:
                continue
            check_id = str(check.get("id") or "")
            component = self._component_for(check_id)
            if component:
                suggestions.append(
                    {
                        "component": component,
                        "label": str(check.get("label") or component),
                        "detail": self._human_plan(component),
                    }
                )
        # Deduplicate while keeping order.
        seen: set[str] = set()
        unique = []
        for item in suggestions:
            if item["component"] in seen:
                continue
            seen.add(item["component"])
            unique.append(item)
        return {
            "ok": True,
            "state": "success",
            "components": unique,
            "detail": (
                "Jarvis a trouvé des réparations sûres à proposer."
                if unique
                else "Aucune réparation automatique sûre n'est nécessaire."
            ),
        }

    def repair(self, components: list[str]) -> dict[str, object]:
        requested = []
        for component in components[:8]:
            normalized = str(component).strip().casefold()
            if normalized and normalized not in requested:
                requested.append(normalized)
        results: list[RepairResult] = []
        for component in requested:
            gate = self._acquire_attempt(component)
            if gate is not None:
                results.append(gate)
                continue
            handler = {
                "storage": self._repair_storage,
                "voice": self._repair_voice,
                "local_ai": self._repair_local_ai,
                "thunderbird_bridge": self._repair_thunderbird_bridge,
                "browser": self._repair_browser,
            }.get(component)
            if handler is None:
                result = RepairResult(component, "failed", "Cette réparation n'est pas autorisée automatiquement.")
            else:
                result = handler()
            self._record_result(component, result)
            results.append(result)
        states = {item.state for item in results}
        overall = "success" if states == {"success"} else ("partial" if "success" in states else "failed")
        return {
            "ok": bool(results) and overall != "failed",
            "state": overall,
            "results": [item.to_dict() for item in results],
            "detail": self._summary(results),
        }

    def _repair_storage(self) -> RepairResult:
        try:
            for folder in (
                settings.runtime_dir,
                settings.runtime_dir / "voice",
                settings.runtime_dir / "downloads",
                settings.runtime_dir / "browser-sessions",
            ):
                folder.mkdir(parents=True, exist_ok=True)
            marker = settings.runtime_dir / ".repair-write-test"
            marker.write_text("ok", encoding="utf-8")
            marker.unlink(missing_ok=True)
        except OSError as exc:
            return RepairResult("storage", "failed", f"Le stockage reste inaccessible : {type(exc).__name__}.")
        return RepairResult("storage", "success", "Le stockage local de Jarvis est de nouveau accessible.")

    def _repair_voice(self) -> RepairResult:
        try:
            voice_service.stop(clear_queue=True)
            voice_service.shutdown()
            restarted = voice_service.prewarm_async()
        except (OSError, RuntimeError) as exc:
            return RepairResult("voice", "failed", f"Le moteur vocal n'a pas pu être relancé : {type(exc).__name__}.")
        if restarted:
            return RepairResult("voice", "success", "Le moteur vocal local a été relancé et se prépare en arrière-plan.")
        providers = voice_service.status().get("providers")
        if isinstance(providers, dict) and any(
            isinstance(value, dict) and value.get("available") for value in providers.values()
        ):
            return RepairResult("voice", "success", "Une voix de secours reste disponible et Jarvis peut continuer à parler.")
        return RepairResult("voice", "failed", "Aucun moteur vocal n'est disponible après la tentative de réparation.")

    def _repair_local_ai(self) -> RepairResult:
        if local_ai.ready():
            return RepairResult("local_ai", "success", "L'IA locale répond déjà correctement.")
        executable = shutil.which("ollama") or shutil.which("ollama.exe")
        if not executable:
            return RepairResult(
                "local_ai",
                "failed",
                "Ollama n'est pas installé. Jarvis reste utilisable en mode de secours sans télécharger quoi que ce soit automatiquement.",
            )
        try:
            subprocess.Popen(
                [executable, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            return RepairResult("local_ai", "failed", f"Ollama n'a pas pu être relancé : {type(exc).__name__}.")
        for _ in range(8):
            time.sleep(0.5)
            if local_ai.ready():
                return RepairResult("local_ai", "success", "L'IA locale a été relancée.")
        return RepairResult(
            "local_ai",
            "failed",
            "Ollama a été relancé mais le modèle local n'est pas prêt. Jarvis continue en mode de secours.",
        )

    def _repair_thunderbird_bridge(self) -> RepairResult:
        if sys.platform != "win32":
            return RepairResult("thunderbird_bridge", "failed", "Cette réparation est disponible uniquement sur Windows.")
        native_host = self._installed_native_host()
        if native_host is None:
            return RepairResult("thunderbird_bridge", "failed", "JarvisNativeHost.exe est introuvable dans l'installation.")
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return RepairResult("thunderbird_bridge", "failed", "Le profil Windows APPDATA est introuvable.")
        manifest_path = (
            Path(appdata)
            / "Mozilla"
            / "NativeMessagingHosts"
            / f"{settings.thunderbird_native_host_name}.json"
        )
        manifest = {
            "name": settings.thunderbird_native_host_name,
            "description": "Pont local entre Thunderbird et Jarvis Papa",
            "path": str(native_host),
            "type": "stdio",
            "allowed_extensions": ["jarvis-papa@local"],
        }
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = manifest_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(manifest_path)
            import winreg

            key_name = rf"Software\Mozilla\NativeMessagingHosts\{settings.thunderbird_native_host_name}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_name) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest_path))
        except (ImportError, OSError) as exc:
            return RepairResult("thunderbird_bridge", "failed", f"Le pont Thunderbird n'a pas pu être réparé : {type(exc).__name__}.")
        return RepairResult(
            "thunderbird_bridge",
            "success",
            "Le pont Thunderbird a été réenregistré. Ouvre Thunderbird pour vérifier le signal de vie.",
        )

    def _repair_browser(self) -> RepairResult:
        if sys.platform != "win32":
            return RepairResult("browser", "failed", "Cette réparation est disponible uniquement sur Windows.")
        candidates = [
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        if any(path.is_file() for path in candidates):
            return RepairResult("browser", "success", "Microsoft Edge est disponible pour l'automatisation Web.")
        return RepairResult(
            "browser",
            "failed",
            "Microsoft Edge n'a pas été trouvé. Jarvis ne télécharge pas silencieusement un navigateur.",
        )

    def _acquire_attempt(self, component: str) -> RepairResult | None:
        now = time.time()
        state = self._load_state()
        entry = state.get(component) if isinstance(state.get(component), dict) else {}
        open_until = float(entry.get("open_until") or 0.0)
        if open_until > now:
            return RepairResult(
                component,
                "failed",
                "J'ai déjà essayé plusieurs fois récemment. J'arrête les redémarrages automatiques pour éviter une boucle.",
                int(entry.get("attempts") or 0),
            )
        window_started = float(entry.get("window_started") or now)
        attempts = int(entry.get("attempts") or 0)
        if now - window_started > self.WINDOW_SECONDS:
            window_started = now
            attempts = 0
        attempts += 1
        if attempts > self.MAX_ATTEMPTS:
            entry = {
                "attempts": attempts,
                "window_started": window_started,
                "open_until": now + self.CIRCUIT_SECONDS,
                "last_state": "circuit_open",
            }
            state[component] = entry
            self._save_state(state)
            return RepairResult(
                component,
                "failed",
                "La réparation automatique est temporairement suspendue après plusieurs échecs.",
                attempts,
            )
        state[component] = {
            "attempts": attempts,
            "window_started": window_started,
            "open_until": 0.0,
            "last_state": "attempting",
        }
        self._save_state(state)
        return None

    def _record_result(self, component: str, result: RepairResult) -> None:
        state = self._load_state()
        entry = state.get(component) if isinstance(state.get(component), dict) else {}
        entry["last_state"] = result.state
        entry["last_at"] = time.time()
        if result.ok:
            entry["attempts"] = 0
            entry["open_until"] = 0.0
        state[component] = entry
        self._save_state(state)

    def _load_state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, payload: dict[str, object]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            pass

    @staticmethod
    def _component_for(check_id: str) -> str | None:
        mapping = {
            "runtime_storage": "storage",
            "voice": "voice",
            "local_ai": "local_ai",
            "browser": "browser",
            "native_manifest": "thunderbird_bridge",
            "native_registry": "thunderbird_bridge",
            "thunderbird_bridge": "thunderbird_bridge",
        }
        return mapping.get(check_id)

    @staticmethod
    def _human_plan(component: str) -> str:
        return {
            "storage": "Vérifier et recréer les dossiers locaux nécessaires.",
            "voice": "Arrêter proprement le moteur vocal puis le relancer une seule fois.",
            "local_ai": "Relancer Ollama s'il est déjà installé, sans télécharger de modèle automatiquement.",
            "browser": "Vérifier que Microsoft Edge est disponible pour l'automatisation.",
            "thunderbird_bridge": "Réenregistrer le Native Messaging Host de Thunderbird dans le profil Windows.",
        }.get(component, "Réparation limitée.")

    @staticmethod
    def _installed_native_host() -> Path | None:
        candidates = []
        executable_dir = Path(sys.executable).resolve().parent
        candidates.append(executable_dir / "JarvisNativeHost.exe")
        candidates.append(Path(__file__).resolve().parents[2] / "dist" / "JarvisNativeHost.exe")
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def _summary(results: list[RepairResult]) -> str:
        if not results:
            return "Aucune réparation n'a été demandée."
        succeeded = sum(item.state == "success" for item in results)
        if succeeded == len(results):
            return "Les réparations demandées ont été effectuées. Jarvis va revérifier les composants."
        if succeeded:
            return "Certaines réparations ont réussi, d'autres restent à vérifier manuellement."
        return "Je n'ai pas réussi à réparer ces composants automatiquement. Jarvis reste utilisable avec les fonctions disponibles."


repair_service = RepairService()
