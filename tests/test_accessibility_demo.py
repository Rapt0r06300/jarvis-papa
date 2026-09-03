from __future__ import annotations

import sys

import pytest


def test_p9_16_windows_175_percent_keeps_required_actions_accessible_with_scrolling() -> None:
    from jarvis_papa.accessibility_demo import certify_large_scale

    result = certify_large_scale(scale_percent=175, viewport=(1366, 768))

    assert result.required_actions_accessible is True
    assert result.scrolling_available is True
    assert result.hidden_required_controls == ()


def test_p9_17_keyboard_only_core_flow_has_logical_focus_and_activation() -> None:
    from jarvis_papa.accessibility_demo import build_keyboard_contract

    contract = build_keyboard_contract(("Today", "Decisions", "Search", "Action principale"))

    assert contract.focus_order == ("Today", "Decisions", "Search", "Action principale")
    assert {"Tab", "Shift+Tab", "Enter", "Space", "Escape"}.issubset(contract.keys)
    assert contract.mouse_required is False


def test_p9_18_priority_state_has_text_icon_and_readable_contrast() -> None:
    from jarvis_papa.accessibility_demo import build_accessible_state_cue

    cue = build_accessible_state_cue("high")

    assert "priorité" in cue.label.lower()
    assert cue.icon.strip()
    assert cue.relies_on_color_only is False
    assert cue.contrast_ratio >= 4.5


def test_p9_19_core_workflow_survives_microphone_and_tts_outage_visually() -> None:
    from jarvis_papa.accessibility_demo import voice_fallback

    result = voice_fallback(
        microphone_available=False,
        tts_available=False,
        event_backed_update="Colis disponible au relais jusqu’à vendredi.",
    )

    assert result.core_workflow_available is True
    assert result.microphone_required is False
    assert result.visual_text == "Colis disponible au relais jusqu’à vendredi."
    assert result.spoken is False


def test_p9_20_synthetic_demo_is_offline_fake_and_counters_are_measured() -> None:
    from jarvis_papa.accessibility_demo import build_synthetic_robert_demo

    demo = build_synthetic_robert_demo(seed=42)

    assert demo.synthetic is True
    assert demo.offline is True
    assert demo.real_account_data_present is False
    assert {event.kind for event in demo.events} == {
        "noise_filtered",
        "buyer_offer",
        "parcel_pickup",
        "bank_review",
    }
    assert demo.counters.processed == len(demo.events)
    assert demo.counters.surfaced == sum(1 for event in demo.events if event.surfaced)
    assert all("example" in event.source for event in demo.events)
