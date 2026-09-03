from __future__ import annotations

from pathlib import Path


def test_p8_11_retention_policy_is_explicit_and_highly_sensitive_is_forbidden() -> None:
    from jarvis_papa.memory_controls import RetentionMode, retention_policy

    assert retention_policy("public").mode is RetentionMode.DURABLE
    assert retention_policy("personal").mode is RetentionMode.DURABLE
    assert retention_policy("sensitive").mode is RetentionMode.BOUNDED
    assert retention_policy("highly_sensitive").mode is RetentionMode.FORBIDDEN
    assert retention_policy("highly_sensitive").may_promote is False


def test_p8_12_pickup_code_expires_and_completion_invalidates_without_durable_memory() -> None:
    from jarvis_papa.memory_controls import PickupCodeRetention

    vault = PickupCodeRetention(default_ttl_seconds=60)
    vault.retain("parcel-1", "482731", now=100.0)
    assert vault.get("parcel-1", now=120.0) == "482731"
    assert vault.get("parcel-1", now=161.0) is None

    vault.retain("parcel-2", "ABC9", now=200.0)
    vault.complete("parcel-2")
    assert vault.get("parcel-2", now=201.0) is None
    assert vault.durable_memory_payload() == ()


def test_p8_13_memory_boundary_rejects_cookie_and_2fa_secrets(tmp_path: Path) -> None:
    from jarvis_papa.memory import MemoryStore

    store = MemoryStore(tmp_path / "memory.sqlite3")
    cookie = store.remember("email", "cookie", "sessionid=very-secret-session-cookie")
    otp = store.remember("email", "verification", "code 2FA 123456")

    assert cookie.sanitized is True
    assert cookie.reason == "secret_redacted"
    assert "very-secret" not in cookie.value
    assert otp.sanitized is True
    assert "123456" not in otp.value


def test_p8_14_preference_card_is_plain_french_and_marks_tentative_learning() -> None:
    from jarvis_papa.memory_controls import render_preference_card

    tentative = render_preference_card(
        label="réponses courtes aux acheteurs",
        confidence=0.55,
        source_count=2,
    )
    assert "Tu préfères" in tentative.title
    assert "2" in tentative.detail
    assert "à confirmer" in tentative.detail.casefold()

    strong = render_preference_card(
        label="réponses courtes aux acheteurs",
        confidence=0.92,
        source_count=6,
    )
    assert "à confirmer" not in strong.detail.casefold()


def test_p8_15_correct_and_forget_are_targeted_and_user_authoritative() -> None:
    from jarvis_papa.memory_controls import PreferenceControls

    controls = PreferenceControls()
    controls.correct("draft:buyers", "court et direct", evidence_id="user-1")
    controls.correct("reminder:parcels", "rappeler le matin", evidence_id="user-2")

    draft = controls.get("draft:buyers")
    assert draft is not None
    assert draft.provenance == "explicit_user_correction"
    assert draft.confidence == 1.0

    controls.forget("draft:buyers")
    assert controls.get("draft:buyers") is None
    assert controls.get("reminder:parcels") is not None
    assert "draft:buyers" not in controls.context_for("draft:buyers")
