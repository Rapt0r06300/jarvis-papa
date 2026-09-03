from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest


def test_p9_11_timeline_is_normalized_and_keeps_expandable_source_evidence() -> None:
    from jarvis_papa.ux_explainability import TimelineEvent, build_timeline

    events = (
        TimelineEvent("relay", "Disponible au relais", datetime(2026, 9, 3, 10, tzinfo=timezone.utc), "mail-relay"),
        TimelineEvent("order", "Commande créée", datetime(2026, 9, 1, 8, tzinfo=timezone.utc), "amazon-order"),
        TimelineEvent("shipment", "Expédiée", datetime(2026, 9, 2, 9, tzinfo=timezone.utc), "carrier-event"),
    )
    timeline = build_timeline(events)

    assert [item.kind for item in timeline] == ["order", "shipment", "relay"]
    assert [item.source_id for item in timeline] == ["amazon-order", "carrier-event", "mail-relay"]
    assert all(item.source_expandable for item in timeline)


def test_p9_12_why_explanation_comes_from_real_priority_factor() -> None:
    from jarvis_papa.ux_explainability import explain_why

    explanation = explain_why({"pickup_deadline": "vendredi", "source": "Mondial Relay"})

    assert "vendredi" in explanation.lower()
    assert "retrait" in explanation.lower() or "colis" in explanation.lower()
    assert "modèle" not in explanation.lower()


def test_p9_13_uncertainty_copy_is_natural_and_non_categorical_when_not_confirmed() -> None:
    from jarvis_papa.ux_explainability import humanize_confidence

    likely = humanize_confidence("lié à la commande Amazon", 0.72)
    confirmed = humanize_confidence("lié à la commande Amazon", 1.0)
    low = humanize_confidence("lié à la commande Amazon", 0.30)

    assert "je pense" in likely.lower()
    assert confirmed == "Lié à la commande Amazon."
    assert "pas certain" in low.lower() or "incertain" in low.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPI certification")
def test_p9_14_windows_125_percent_layout_keeps_actions_and_focus_visible() -> None:
    from jarvis_papa.ux_explainability import certify_layout

    result = certify_layout(scale_percent=125, viewport=(1366, 768))

    assert result.primary_actions_accessible is True
    assert result.text_clipped is False
    assert result.focus_visible is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPI certification")
def test_p9_15_windows_150_percent_layout_keeps_navigation_cards_and_dialogs_usable() -> None:
    from jarvis_papa.ux_explainability import certify_layout

    result = certify_layout(scale_percent=150, viewport=(1366, 768))

    assert result.navigation_usable is True
    assert result.cards_usable is True
    assert result.dialog_fits is True
