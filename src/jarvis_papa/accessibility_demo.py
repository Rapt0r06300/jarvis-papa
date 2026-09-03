from __future__ import annotations

from dataclasses import dataclass
from random import Random

from .ux_explainability import certify_layout


@dataclass(frozen=True, slots=True)
class LargeScaleCertification:
    scale_percent: int
    required_actions_accessible: bool
    scrolling_available: bool
    hidden_required_controls: tuple[str, ...]


def certify_large_scale(*, scale_percent: int, viewport: tuple[int, int]) -> LargeScaleCertification:
    base = certify_layout(scale_percent=scale_percent, viewport=viewport)
    hidden = () if base.primary_actions_accessible else ("primary_action",)
    return LargeScaleCertification(
        scale_percent=scale_percent,
        required_actions_accessible=base.primary_actions_accessible,
        scrolling_available=base.scrolling_required or base.dialog_fits,
        hidden_required_controls=hidden,
    )


@dataclass(frozen=True, slots=True)
class KeyboardContract:
    focus_order: tuple[str, ...]
    keys: frozenset[str]
    mouse_required: bool


def build_keyboard_contract(focus_order: tuple[str, ...]) -> KeyboardContract:
    if not focus_order or any(not item.strip() for item in focus_order):
        raise ValueError("focus_order must contain visible controls")
    return KeyboardContract(
        focus_order=focus_order,
        keys=frozenset({"Tab", "Shift+Tab", "Enter", "Space", "Escape"}),
        mouse_required=False,
    )


@dataclass(frozen=True, slots=True)
class AccessibleStateCue:
    label: str
    icon: str
    contrast_ratio: float
    relies_on_color_only: bool = False


def build_accessible_state_cue(priority: str) -> AccessibleStateCue:
    normalized = priority.strip().casefold()
    values = {
        "high": ("Priorité haute", "!", 7.0),
        "medium": ("Priorité normale", "•", 5.2),
        "low": ("Priorité faible", "↓", 4.8),
    }
    label, icon, contrast = values.get(normalized, ("Priorité à vérifier", "?", 4.5))
    return AccessibleStateCue(label=label, icon=icon, contrast_ratio=contrast)


@dataclass(frozen=True, slots=True)
class VoiceFallbackResult:
    core_workflow_available: bool
    microphone_required: bool
    visual_text: str
    spoken: bool


def voice_fallback(
    *,
    microphone_available: bool,
    tts_available: bool,
    event_backed_update: str,
) -> VoiceFallbackResult:
    del microphone_available
    text = event_backed_update.strip()
    return VoiceFallbackResult(
        core_workflow_available=True,
        microphone_required=False,
        visual_text=text,
        spoken=bool(tts_available and text),
    )


@dataclass(frozen=True, slots=True)
class SyntheticDemoEvent:
    event_id: str
    kind: str
    source: str
    surfaced: bool


@dataclass(frozen=True, slots=True)
class SyntheticDemoCounters:
    processed: int
    surfaced: int


@dataclass(frozen=True, slots=True)
class SyntheticRobertDemo:
    synthetic: bool
    offline: bool
    real_account_data_present: bool
    events: tuple[SyntheticDemoEvent, ...]
    counters: SyntheticDemoCounters


def build_synthetic_robert_demo(*, seed: int) -> SyntheticRobertDemo:
    rng = Random(seed)
    kinds = (
        ("noise_filtered", "newsletter@example.invalid", False),
        ("buyer_offer", "buyer@example.invalid", True),
        ("parcel_pickup", "carrier@example.invalid", True),
        ("bank_review", "bank-fixture@example.invalid", True),
    )
    events = tuple(
        SyntheticDemoEvent(
            event_id=f"demo-{index}-{rng.randrange(10_000):04d}",
            kind=kind,
            source=source,
            surfaced=surfaced,
        )
        for index, (kind, source, surfaced) in enumerate(kinds, start=1)
    )
    return SyntheticRobertDemo(
        synthetic=True,
        offline=True,
        real_account_data_present=False,
        events=events,
        counters=SyntheticDemoCounters(
            processed=len(events),
            surfaced=sum(1 for event in events if event.surfaced),
        ),
    )
