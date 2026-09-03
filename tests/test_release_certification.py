from __future__ import annotations


def test_p10_16_tts_outage_keeps_full_synthetic_day_visual_and_non_blocking() -> None:
    from jarvis_papa.release_certification import run_tts_outage_day

    result = run_tts_outage_day(event_count=150, tts_available=False)

    assert result.completed_events == 150
    assert result.core_workflow_blocked is False
    assert result.spoken_events == 0
    assert result.visible_critical_events == result.critical_events
    assert result.briefing_visible is True
    assert result.decisions_visible is True


def test_p10_17_windows_accessibility_gate_requires_125_150_175_and_fails_blocking_issue() -> None:
    from jarvis_papa.release_certification import AccessibilitySample, certify_windows_accessibility

    samples = (
        AccessibilitySample(1.25, no_blocking_clipping=True, keyboard_accessible=True, readable=True),
        AccessibilitySample(1.50, no_blocking_clipping=True, keyboard_accessible=True, readable=True),
        AccessibilitySample(1.75, no_blocking_clipping=False, keyboard_accessible=True, readable=True),
    )
    result = certify_windows_accessibility(samples)

    assert result.required_scale_factors == (1.25, 1.5, 1.75)
    assert result.tested_scale_factors == (1.25, 1.5, 1.75)
    assert result.release_gate_passed is False
    assert "1.75" in result.blocking_failures[0]


def test_p10_18_autopilot_smoke_manifest_includes_runtime_and_protected_route() -> None:
    from jarvis_papa.release_certification import autopilot_runtime_manifest, build_autopilot_smoke

    manifest = autopilot_runtime_manifest()
    smoke = build_autopilot_smoke()

    assert "jarvis_papa.situations" in manifest.required_modules
    assert "jarvis_papa.robert_surfaces" in manifest.required_modules
    assert "jarvis_papa.decision_cards" in manifest.required_modules
    assert manifest.protected_route == "/api/robert/autopilot/smoke"
    assert manifest.auth_required is True
    assert smoke.situation_ingested is True
    assert smoke.briefing
    assert smoke.decision_card_title


def test_p10_18_autopilot_smoke_route_requires_local_api_token_and_executes(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("JARVIS_LOCAL_API_TOKEN", "release-smoke-token")
    from jarvis_papa.app import app

    client = TestClient(app)
    denied = client.get("/api/robert/autopilot/smoke")
    allowed = client.get(
        "/api/robert/autopilot/smoke",
        headers={"Authorization": "Bearer release-smoke-token"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["situation_ingested"] is True
    assert payload["briefing"]
    assert payload["decision_card_title"]
    assert payload["external_action_allowed"] is False


def test_p10_19_restore_preserves_situations_but_drops_ephemeral_authorization_and_secrets() -> None:
    from jarvis_papa.release_certification import sanitize_restored_state

    restored = sanitize_restored_state(
        {
            "situations": {"parcel-1": {"state": "pickup"}},
            "preferences": {"briefing": "short"},
            "authorization_token": "must-not-return",
            "pending_approvals": ["send-mail"],
            "otp": "123456",
            "session_cookie": "secret-cookie",
        }
    )

    assert restored["situations"]["parcel-1"]["state"] == "pickup"
    assert restored["preferences"]["briefing"] == "short"
    assert "authorization_token" not in restored
    assert "pending_approvals" not in restored
    assert "otp" not in restored
    assert "session_cookie" not in restored


def test_p10_20_final_release_gate_rejects_unsigned_or_real_pc_unvalidated_candidate() -> None:
    from jarvis_papa.release_certification import final_release_gate

    blocked = final_release_gate(
        source_sha="abc123",
        windows_run_id="33780000000",
        installer_sha256="f" * 64,
        authenticode_signed=False,
        synthetic_windows_e2e_passed=True,
        real_pc_validated=False,
        real_pc_results={"thunderbird": "not-run", "startup": "not-run"},
    )

    assert blocked.status == "BLOCKED"
    assert blocked.production_ready is False
    assert blocked.source_sha == "abc123"
    assert blocked.windows_run_id == "33780000000"
    assert blocked.installer_sha256 == "f" * 64
    assert "unsigned" in blocked.blockers
    assert "real-pc-unvalidated" in blocked.blockers
