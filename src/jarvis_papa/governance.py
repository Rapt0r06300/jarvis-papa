from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from jarvis_papa.config import settings


class RiskLevel(StrEnum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


@dataclass(frozen=True, slots=True)
class ActionContract:
    """Immutable description of an exact action before execution."""

    action_key: str
    description: str
    binding: dict[str, object]
    risk: RiskLevel
    read_only: bool
    reversible: bool = False
    expected_proof: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    created_at: float = 0.0
    expires_at: float = 0.0

    @classmethod
    def create(
        cls,
        *,
        action_key: str,
        description: str,
        binding: dict[str, object] | None = None,
        risk: RiskLevel = RiskLevel.LOW,
        read_only: bool = True,
        reversible: bool = False,
        expected_proof: tuple[str, ...] = (),
        timeout_seconds: float = 30.0,
        ttl_seconds: float = 180.0,
    ) -> ActionContract:
        now = time.time()
        return cls(
            action_key=action_key.strip()[:160],
            description=" ".join(description.split()).strip()[:1200],
            binding=_normalize(binding or {}),
            risk=risk,
            read_only=bool(read_only),
            reversible=bool(reversible),
            expected_proof=tuple(str(item)[:100] for item in expected_proof[:12]),
            timeout_seconds=max(0.5, min(float(timeout_seconds), 600.0)),
            created_at=now,
            expires_at=now + max(5.0, min(float(ttl_seconds), 900.0)),
        )

    @property
    def digest(self) -> str:
        payload = {
            "action_key": self.action_key,
            "description": self.description,
            "binding": self.binding,
            "risk": self.risk.value,
            "read_only": self.read_only,
            "reversible": self.reversible,
            "expected_proof": self.expected_proof,
            "timeout_seconds": self.timeout_seconds,
            "created_at": round(self.created_at, 3),
            "expires_at": round(self.expires_at, 3),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def expired(self) -> bool:
        return self.expires_at < time.time()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["risk"] = self.risk.value
        payload["digest"] = self.digest
        return payload


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    contract: ActionContract
    steps: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    simulation_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract.to_dict(),
            "steps": list(self.steps),
            "warnings": list(self.warnings),
            "simulation_only": self.simulation_only,
        }


@dataclass(frozen=True, slots=True)
class PolicyResult:
    verdict: PolicyVerdict
    reason: str
    contract_digest: str

    @property
    def allowed(self) -> bool:
        return self.verdict is PolicyVerdict.ALLOW

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "contract_digest": self.contract_digest,
            "allowed": self.allowed,
        }


class KillSwitch:
    """Persistent emergency brake. Activating it is always immediate."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "kill-switch.json")
        self._lock = threading.Lock()

    def activate(self, reason: str = "Arrêt demandé par l'utilisateur.") -> dict[str, object]:
        payload = {
            "active": True,
            "reason": " ".join(reason.split()).strip()[:500],
            "activated_at": time.time(),
        }
        self._write(payload)
        return self.status()

    def clear(self) -> dict[str, object]:
        self._write({"active": False, "reason": "", "activated_at": None})
        return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {"active": False, "reason": "", "activated_at": None}
            except (OSError, json.JSONDecodeError):
                return {
                    "active": True,
                    "reason": "État du bouton d'arrêt illisible : mutations bloquées par sécurité.",
                    "activated_at": None,
                    "state_corrupt": True,
                }
        return payload if isinstance(payload, dict) else {"active": True, "state_corrupt": True}

    def allows(self, contract: ActionContract) -> bool:
        state = self.status()
        if not state.get("active"):
            return True
        return contract.read_only or contract.action_key in {
            "jarvis.kill_switch.activate",
            "voice.stop",
            "agent.cancel",
            "diagnostic.read",
        }

    def _write(self, payload: dict[str, object]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)


class CircuitBreakerRegistry:
    """Small local circuit breakers for flaky subsystems."""

    FAILURE_THRESHOLD = 3
    WINDOW_SECONDS = 120.0
    OPEN_SECONDS = 60.0

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "circuit-breakers.json")
        self._lock = threading.Lock()

    def allow(self, component: str) -> bool:
        entry = self._entry(component)
        return float(entry.get("open_until") or 0.0) <= time.time()

    def record_success(self, component: str) -> None:
        state = self._load()
        state[self._key(component)] = {
            "failures": 0,
            "window_started": time.time(),
            "open_until": 0.0,
            "last_state": "success",
        }
        self._save(state)

    def record_failure(self, component: str) -> None:
        now = time.time()
        state = self._load()
        key = self._key(component)
        entry = state.get(key) if isinstance(state.get(key), dict) else {}
        window_started = float(entry.get("window_started") or now)
        failures = int(entry.get("failures") or 0)
        if now - window_started > self.WINDOW_SECONDS:
            window_started = now
            failures = 0
        failures += 1
        open_until = now + self.OPEN_SECONDS if failures >= self.FAILURE_THRESHOLD else 0.0
        state[key] = {
            "failures": failures,
            "window_started": window_started,
            "open_until": open_until,
            "last_state": "open" if open_until else "failure",
        }
        self._save(state)

    def snapshot(self) -> dict[str, object]:
        now = time.time()
        state = self._load()
        return {
            key: {
                **value,
                "open": float(value.get("open_until") or 0.0) > now,
            }
            for key, value in state.items()
            if isinstance(value, dict)
        }

    def _entry(self, component: str) -> dict[str, object]:
        state = self._load()
        value = state.get(self._key(component))
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _key(component: str) -> str:
        clean = "".join(ch for ch in component.casefold() if ch.isalnum() or ch in "._-")
        return clean[:100] or "component"

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
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                return


class PolicyKernel:
    """Framework-agnostic deterministic policy gate for every capability."""

    UNTRUSTED_SOURCES = frozenset({"mail", "web", "document", "memory", "tool"})

    def __init__(self, switch: KillSwitch | None = None) -> None:
        self.switch = switch or KillSwitch()

    def evaluate(
        self,
        contract: ActionContract,
        *,
        authorization_present: bool = False,
        source: str = "local",
    ) -> PolicyResult:
        digest = contract.digest
        if contract.expired:
            return PolicyResult(PolicyVerdict.DENY, "Le contrat d'action a expiré.", digest)
        if not self.switch.allows(contract):
            return PolicyResult(
                PolicyVerdict.DENY,
                "Le bouton d'arrêt global est actif : les modifications sont bloquées.",
                digest,
            )
        if source.casefold() in self.UNTRUSTED_SOURCES and not contract.read_only and not authorization_present:
            return PolicyResult(
                PolicyVerdict.REQUIRE_CONFIRMATION,
                "Une donnée externe ne peut jamais déclencher seule une modification.",
                digest,
            )
        risky = not contract.read_only or contract.risk in {
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }
        if risky and not authorization_present:
            return PolicyResult(
                PolicyVerdict.REQUIRE_CONFIRMATION,
                "Cette action modifie un état et exige les deux autorisations exactes.",
                digest,
            )
        return PolicyResult(PolicyVerdict.ALLOW, "Action autorisée par la politique locale.", digest)

    @staticmethod
    def simulate(
        contract: ActionContract,
        steps: list[str] | tuple[str, ...],
        warnings: list[str] | tuple[str, ...] = (),
    ) -> ExecutionPlan:
        return ExecutionPlan(
            contract=contract,
            steps=tuple(" ".join(str(step).split()).strip()[:500] for step in steps[:20]),
            warnings=tuple(" ".join(str(item).split()).strip()[:500] for item in warnings[:10]),
            simulation_only=True,
        )


def _normalize(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return format(value, ".12g")
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return str(value)


kill_switch = KillSwitch()
circuit_breakers = CircuitBreakerRegistry()
policy_kernel = PolicyKernel(kill_switch)
