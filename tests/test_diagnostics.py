import importlib

from jarvis_papa.config import settings
from jarvis_papa.thunderbird import ThunderbirdBridgeState


def test_diagnostics_report_contains_operational_checks(tmp_path, monkeypatch) -> None:
    module = importlib.import_module("jarvis_papa.diagnostics")
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(
        module.local_ai,
        "status",
        lambda: {
            "enabled": True,
            "available": False,
            "provider": "ollama",
            "model": "qwen3:4b",
        },
    )
    monkeypatch.setattr(
        module.voice_service,
        "status",
        lambda: {
            "enabled": True,
            "providers": {"windows": {"available": False}},
        },
    )

    report = module.JarvisDiagnostics().run()
    ids = {item["id"] for item in report["checks"]}

    assert report["status"] in {"ok", "degraded"}
    assert report["ready"] is True
    assert 0 <= report["score"] <= 100
    assert {
        "local_security",
        "runtime_storage",
        "file_search",
        "browser",
        "local_ai",
        "voice",
        "thunderbird_install",
        "native_manifest",
        "native_registry",
        "thunderbird_bridge",
        "thunderbird_commands",
    } <= ids


def test_thunderbird_bridge_state_reports_recent_heartbeat() -> None:
    state = ThunderbirdBridgeState()
    assert state.snapshot()["connected"] is False

    state.mark_seen("test-native-host")
    snapshot = state.snapshot(timeout_seconds=5)

    assert snapshot["connected"] is True
    assert snapshot["source"] == "test-native-host"
    assert isinstance(snapshot["age_seconds"], float)
