import time
from pathlib import Path
from threading import Event

from jarvis_papa.config import settings
from jarvis_papa.voice.providers import VoiceArtifact
from jarvis_papa.voice.service import VoiceProvider, VoiceService


class FakeProvider(VoiceProvider):
    name = "fake"

    @property
    def available(self) -> bool:
        return True

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        path = output_stem.with_suffix(".wav")
        path.write_bytes(b"RIFFfake")
        return VoiceArtifact(self.name, path, "audio/wav")


class FastPlayer:
    def play(self, path: Path, duration_seconds: float) -> bool:
        return path.exists()

    def stop(self) -> bool:
        return True


class BlockingPlayer:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.stop_called = False

    def play(self, path: Path, duration_seconds: float) -> bool:
        self.started.set()
        self.release.wait(timeout=1.0)
        return path.exists()

    def stop(self) -> bool:
        self.stop_called = True
        self.release.set()
        return True


def _service(tmp_path, monkeypatch) -> VoiceService:
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    monkeypatch.setattr(settings, "voice_provider_order", "fake")
    return VoiceService({"fake": FakeProvider()})


def _wait_for_event(service: VoiceService, event_type: str, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(event.get("type") == event_type for event in service.events.after(0)):
            return True
        time.sleep(0.01)
    return False


def test_long_speech_is_split_into_bounded_chunks() -> None:
    text = " ".join(["phrase assez longue pour tester la découpe."] * 40)
    chunks = VoiceService._split_text(text, limit=120)

    assert len(chunks) > 1
    assert all(1 <= len(chunk) <= 120 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ").strip() == text.strip()


def test_voice_emits_real_started_and_finished_events(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    service.player = FastPlayer()
    try:
        result = service.speak("Bonjour Robert. La voix fonctionne.")
        assert result.ok is True
        assert _wait_for_event(service, "speech_started")
        assert _wait_for_event(service, "speech_finished")
        event_types = {event.get("type") for event in service.events.after(0)}
        assert "speech_queued" in event_types
        assert "speech_started" in event_types
        assert "speech_finished" in event_types
    finally:
        service.shutdown()


def test_critical_speech_preempts_lower_priority_speech(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    player = BlockingPlayer()
    service.player = player
    try:
        first = service.speak("Message normal en cours.", priority="normal")
        assert first.ok is True
        assert player.started.wait(timeout=1.0)

        critical = service.speak("Alerte importante.", priority="critical")
        assert critical.ok is True
        assert player.stop_called is True
        assert _wait_for_event(service, "speech_interrupted")
    finally:
        player.release.set()
        service.shutdown()
