from pathlib import Path

from jarvis_papa.config import settings
from jarvis_papa.voice.providers import VoiceArtifact
from jarvis_papa.voice.service import VoicePlaybackBus, VoiceProvider, VoiceService


class FakeProvider(VoiceProvider):
    def __init__(self, name: str, *, fail: bool = False, available: bool = True) -> None:
        self.name = name
        self.fail = fail
        self._available = available
        self.calls = 0

    @property
    def available(self) -> bool:
        return self._available

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        path = output_stem.with_suffix(".wav")
        path.write_bytes(b"RIFFfake")
        return VoiceArtifact(self.name, path, "audio/wav")


def test_voice_service_falls_back_to_next_provider(tmp_path, monkeypatch) -> None:
    first = FakeProvider("elevenlabs", fail=True)
    second = FakeProvider("azure")
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "voice_provider_order", "elevenlabs,azure")

    service = VoiceService({"elevenlabs": first, "azure": second})
    result = service.synthesize("Bonjour Robert")

    assert result.ok is True
    assert result.provider == "azure"
    assert first.calls == 1
    assert second.calls == 1
    assert any("elevenlabs" in error for error in result.errors)


def test_voice_service_skips_unavailable_provider(tmp_path, monkeypatch) -> None:
    cloud = FakeProvider("elevenlabs", available=False)
    local = FakeProvider("qwen3")
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "voice_provider_order", "elevenlabs,qwen3")

    service = VoiceService({"elevenlabs": cloud, "qwen3": local})
    result = service.synthesize("Je peux continuer hors ligne.")

    assert result.provider == "qwen3"
    assert cloud.calls == 0
    assert local.calls == 1


def test_voice_playback_bus_returns_only_new_events() -> None:
    bus = VoicePlaybackBus()
    first = bus.publish(text="Premier message", provider="azure", duration=2.0)
    second = bus.publish(text="Deuxième message", provider="qwen3", duration=3.0)

    events = bus.after(first)

    assert second > first
    assert len(events) == 1
    assert events[0]["text"] == "Deuxième message"
    assert events[0]["provider"] == "qwen3"


def test_duration_is_short_and_readable() -> None:
    duration = VoiceService._estimate_duration("Robert, j'ai reçu un mail important de l'assurance.")
    assert 1.6 <= duration <= 10.0
