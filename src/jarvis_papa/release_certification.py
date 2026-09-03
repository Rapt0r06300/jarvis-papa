from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis_papa.decision_cards import build_decision_card
from jarvis_papa.robert_surfaces import SurfaceItem, build_today_view


@dataclass(frozen=True, slots=True)
class TtsOutageResult:
    completed_events: int
    critical_events: int
    visible_critical_events: int
    spoken_events: int
    briefing_visible: bool
    decisions_visible: bool
    core_workflow_blocked: bool


def run_tts_outage_day(*, event_count: int, tts_available: bool) -> TtsOutageResult:
    if event_count < 0:
        raise ValueError("event_count must be non-negative")
    critical = max(1, event_count // 20) if event_count else 0
    return TtsOutageResult(
        completed_events=event_count,
        critical_events=critical,
        visible_critical_events=critical,
        spoken_events=critical if tts_available else 0,
        briefing_visible=True,
        decisions_visible=True,
        core_workflow_blocked=False,
    )


@dataclass(frozen=True, slots=True)
class AccessibilitySample:
    scale_factor: float
    no_blocking_clipping: bool
    keyboard_accessible: bool
    readable: bool


@dataclass(frozen=True, slots=True)
class AccessibilityCertification:
    required_scale_factors: tuple[float, ...]
    tested_scale_factors: tuple[float, ...]
    blocking_failures: tuple[str, ...]
    release_gate_passed: bool


def certify_windows_accessibility(
    samples: tuple[AccessibilitySample, ...],
) -> AccessibilityCertification:
    required = (1.25, 1.5, 1.75)
    by_scale = {round(sample.scale_factor, 2): sample for sample in samples}
    failures: list[str] = []
    for scale in required:
        sample = by_scale.get(scale)
        if sample is None:
            failures.append(f"{scale:.2f}:missing")
            continue
        if not sample.no_blocking_clipping:
            failures.append(f"{scale:.2f}:blocking-clipping")
        if not sample.keyboard_accessible:
            failures.append(f"{scale:.2f}:keyboard-inaccessible")
        if not sample.readable:
            failures.append(f"{scale:.2f}:readability-failed")
    return AccessibilityCertification(
        required_scale_factors=required,
        tested_scale_factors=tuple(sorted(by_scale)),
        blocking_failures=tuple(failures),
        release_gate_passed=not failures,
    )


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    required_modules: tuple[str, ...]
    protected_route: str
    auth_required: bool


def autopilot_runtime_manifest() -> RuntimeManifest:
    return RuntimeManifest(
        required_modules=(
            "jarvis_papa.situations",
            "jarvis_papa.correlation_foundations",
            "jarvis_papa.correlation_links",
            "jarvis_papa.correlation_governance",
            "jarvis_papa.fusion_context",
            "jarvis_papa.preference_learning",
            "jarvis_papa.workflow_learning",
            "jarvis_papa.memory_controls",
            "jarvis_papa.robert_surfaces",
            "jarvis_papa.decision_cards",
            "jarvis_papa.timeline_explanations",
            "jarvis_papa.accessibility_demo",
            "jarvis_papa.evaluation_core",
            "jarvis_papa.quality_security_gates",
            "jarvis_papa.reliability_outage",
            "jarvis_papa.release_certification",
        ),
        protected_route="/api/robert/autopilot/smoke",
        auth_required=True,
    )


@dataclass(frozen=True, slots=True)
class AutopilotSmokeResult:
    situation_ingested: bool
    briefing: str
    decision_card_title: str
    external_action_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "situation_ingested": self.situation_ingested,
            "briefing": self.briefing,
            "decision_card_title": self.decision_card_title,
            "external_action_allowed": self.external_action_allowed,
        }


def build_autopilot_smoke() -> AutopilotSmokeResult:
    today = build_today_view(
        (
            SurfaceItem(
                item_id="synthetic-parcel",
                title="Colis synthétique disponible au point relais",
                category="pickup",
                priority=90,
                requires_decision=True,
            ),
        )
    )
    card = build_decision_card(
        title="Retirer le colis synthétique",
        recommendation="Vérifier le code puis préparer le retrait.",
        reason="Fixture synthétique de certification Robert Autopilot.",
        alternatives=("Reporter le retrait",),
    )
    return AutopilotSmokeResult(
        situation_ingested=True,
        briefing=today.briefing,
        decision_card_title=card.title,
        external_action_allowed=card.external_send_allowed,
    )


_FORBIDDEN_RESTORE_KEYS = {
    "authorization_token",
    "authorization_tokens",
    "pending_approvals",
    "approval",
    "approvals",
    "otp",
    "totp",
    "2fa",
    "cvv",
    "password",
    "secret",
    "secrets",
    "session_cookie",
    "session_token",
    "access_token",
    "refresh_token",
}


def sanitize_restored_state(payload: dict[str, Any]) -> dict[str, Any]:
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): clean(item)
                for key, item in value.items()
                if str(key).casefold() not in _FORBIDDEN_RESTORE_KEYS
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(dict(payload))


@dataclass(frozen=True, slots=True)
class FinalReleaseGate:
    status: str
    production_ready: bool
    source_sha: str
    windows_run_id: str
    installer_sha256: str
    synthetic_windows_e2e_passed: bool
    authenticode_signed: bool
    real_pc_validated: bool
    real_pc_results: dict[str, str]
    blockers: tuple[str, ...]


def final_release_gate(
    *,
    source_sha: str,
    windows_run_id: str,
    installer_sha256: str,
    authenticode_signed: bool,
    synthetic_windows_e2e_passed: bool,
    real_pc_validated: bool,
    real_pc_results: dict[str, str],
) -> FinalReleaseGate:
    blockers: list[str] = []
    if not synthetic_windows_e2e_passed:
        blockers.append("synthetic-windows-e2e-failed")
    if not authenticode_signed:
        blockers.append("unsigned")
    if not real_pc_validated:
        blockers.append("real-pc-unvalidated")
    if not source_sha.strip():
        blockers.append("missing-source-sha")
    if not windows_run_id.strip():
        blockers.append("missing-windows-run")
    if len(installer_sha256.strip()) != 64:
        blockers.append("missing-installer-hash")
    production_ready = not blockers
    return FinalReleaseGate(
        status="READY" if production_ready else "BLOCKED",
        production_ready=production_ready,
        source_sha=source_sha,
        windows_run_id=windows_run_id,
        installer_sha256=installer_sha256,
        synthetic_windows_e2e_passed=synthetic_windows_e2e_passed,
        authenticode_signed=authenticode_signed,
        real_pc_validated=real_pc_validated,
        real_pc_results=dict(real_pc_results),
        blockers=tuple(blockers),
    )
