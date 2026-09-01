from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    total_ram_gb: float | None
    available_ram_gb: float | None
    gpu_vram_total_mb: int | None
    gpu_vram_used_mb: int | None
    pressure: str
    collected_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelDecision:
    route: str
    mode: str
    model: str
    reason: str
    sensitive: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ResourceGovernor:
    """Cheap resource probe used to avoid GPU/RAM contention between LLM and TTS."""

    CACHE_SECONDS = 2.0

    def __init__(self) -> None:
        self._cached: ResourceSnapshot | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> ResourceSnapshot:
        with self._lock:
            if self._cached and time.time() - self._cached.collected_at <= self.CACHE_SECONDS:
                return self._cached
        total, available = self._memory()
        gpu_total, gpu_used = self._gpu_memory()
        pressure = "normal"
        if available is not None and available < 1.5:
            pressure = "critical"
        elif available is not None and available < 3.0:
            pressure = "high"
        if gpu_total and gpu_used is not None:
            free = gpu_total - gpu_used
            if free < 700:
                pressure = "critical"
            elif free < 1600 and pressure == "normal":
                pressure = "high"
        result = ResourceSnapshot(total, available, gpu_total, gpu_used, pressure, time.time())
        with self._lock:
            self._cached = result
        return result

    def voice_keep_warm(self) -> bool:
        state = self.snapshot()
        if state.pressure == "critical":
            return False
        if state.available_ram_gb is not None and state.available_ram_gb < 2.5:
            return False
        if state.gpu_vram_total_mb and state.gpu_vram_used_mb is not None:
            return state.gpu_vram_total_mb - state.gpu_vram_used_mb >= 1400
        return True

    @staticmethod
    def _memory() -> tuple[float | None, float | None]:
        if sys.platform == "win32":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                status = MEMORYSTATUSEX()
                status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    scale = 1024**3
                    return round(status.ullTotalPhys / scale, 2), round(status.ullAvailPhys / scale, 2)
            except (AttributeError, OSError, ValueError):
                pass
        try:
            if Path("/proc/meminfo").is_file():
                values: dict[str, int] = {}
                for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                    key, _, raw = line.partition(":")
                    if key in {"MemTotal", "MemAvailable"}:
                        values[key] = int(raw.strip().split()[0])
                if values:
                    return (
                        round(values.get("MemTotal", 0) / 1024 / 1024, 2),
                        round(values.get("MemAvailable", 0) / 1024 / 1024, 2),
                    )
        except (OSError, ValueError):
            pass
        return None, None

    @staticmethod
    def _gpu_memory() -> tuple[int | None, int | None]:
        executable = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")
        if not executable:
            return None, None
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=memory.total,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=1.2,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        if completed.returncode != 0:
            return None, None
        first = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
        try:
            total, used = [int(item.strip()) for item in first.split(",")[:2]]
        except (ValueError, TypeError):
            return None, None
        return total, used


class ModelRouter:
    """Local-first model selection; sensitive data never opts into cloud by itself."""

    FAST_ROUTES = frozenset({"diagnostic", "mail", "files", "windows"})

    def decide(
        self,
        *,
        route: str,
        prompt: str = "",
        sensitive: bool = False,
        complexity: str = "normal",
    ) -> ModelDecision:
        route_key = route.casefold().strip() or "knowledge"
        if route_key in self.FAST_ROUTES and len(prompt) < 140 and complexity == "simple":
            return ModelDecision(route_key, "deterministic", "deterministic", "Chemin rapide borné.", sensitive)
        fast_model = getattr(settings, "ollama_fast_model", settings.ollama_model)
        reasoning_model = getattr(settings, "ollama_reasoning_model", settings.ollama_model)
        model = reasoning_model if complexity in {"complex", "multi_step"} else fast_model
        return ModelDecision(
            route_key,
            "local",
            model,
            "Données sensibles/local-first." if sensitive else "Modèle local préféré pour confidentialité et disponibilité.",
            sensitive,
        )


class ReliabilityMap:
    """Learns which deterministic capability path works best, without storing user content."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "reliability-map.json")
        self._lock = threading.Lock()

    def record(self, capability: str, path_name: str, *, ok: bool, duration_ms: float = 0.0) -> None:
        state = self._load()
        key = self._key(capability, path_name)
        row = state.get(key) if isinstance(state.get(key), dict) else {}
        success = int(row.get("success") or 0) + (1 if ok else 0)
        failure = int(row.get("failure") or 0) + (0 if ok else 1)
        count = success + failure
        previous = float(row.get("mean_ms") or 0.0)
        mean = previous + (max(0.0, float(duration_ms)) - previous) / max(1, count)
        state[key] = {
            "capability": self._clean(capability),
            "path": self._clean(path_name),
            "success": success,
            "failure": failure,
            "mean_ms": round(mean, 1),
            "updated_at": time.time(),
        }
        self._save(state)

    def rank(self, capability: str, candidates: list[str] | tuple[str, ...]) -> list[str]:
        state = self._load()
        scored: list[tuple[float, int, str]] = []
        for index, name in enumerate(candidates):
            row = state.get(self._key(capability, name))
            if not isinstance(row, dict):
                scored.append((0.5, -index, name))
                continue
            success = int(row.get("success") or 0)
            failure = int(row.get("failure") or 0)
            rate = (success + 1) / (success + failure + 2)
            latency_penalty = min(float(row.get("mean_ms") or 0.0) / 30000.0, 0.2)
            scored.append((rate - latency_penalty, -index, name))
        scored.sort(reverse=True)
        return [item[2] for item in scored]

    def snapshot(self) -> dict[str, object]:
        return self._load()

    @classmethod
    def _key(cls, capability: str, path_name: str) -> str:
        return f"{cls._clean(capability)}::{cls._clean(path_name)}"

    @staticmethod
    def _clean(value: str) -> str:
        clean = "".join(ch for ch in str(value).casefold() if ch.isalnum() or ch in "._-")
        return clean[:100] or "unknown"

    def _load(self) -> dict[str, object]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        return payload if isinstance(payload, dict) else {}

    def _save(self, payload: dict[str, object]) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_suffix(".tmp")
                temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(self.path)
            except OSError:
                return


class WindowsIsolationAdvisor:
    """Safe adapter for Windows agent containment previews.

    It never assumes MXC/Agent Workspace is available. It only exposes a policy
    manifest and readiness information so production behaviour remains unchanged
    until Microsoft ships a stable runtime on the target PC.
    """

    def policy_manifest(self) -> dict[str, object]:
        return {
            "version": 1,
            "identity": "jarvis-papa-local-agent",
            "filesystem": {
                "roots": [str(Path(item).expanduser()) for item in settings.file_search_roots],
                "default": "deny",
            },
            "network": {"default": "deny", "allow_https_for_explicit_web_tasks": True},
            "interactive_desktop": "prefer_user_approved_uia",
            "admin_privileges": "deny",
        }

    def status(self) -> dict[str, object]:
        if sys.platform != "win32":
            return {"supported_os": False, "mode": "not_windows", "active": False}
        return {
            "supported_os": True,
            "mode": "policy_ready_preview_adapter",
            "active": False,
            "detail": "Le confinement Windows agent est préparé mais non activé tant que MXC/Agent Workspace n'est pas stable sur ce PC.",
            "manifest": self.policy_manifest(),
        }


resource_governor = ResourceGovernor()
model_router = ModelRouter()
reliability_map = ReliabilityMap()
windows_isolation = WindowsIsolationAdvisor()
