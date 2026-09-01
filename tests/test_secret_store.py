from __future__ import annotations

import sys
from pathlib import Path

import pytest

import jarvis_papa.secret_store as secret_module
from jarvis_papa.secret_store import DPAPIProtector, EncryptedSecretStore, migrate_legacy_env_secrets


class TestProtector:
    def protect(self, value: bytes) -> bytes:
        return b"JP1:" + bytes((byte ^ 0xA5) for byte in value[::-1])

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"JP1:"):
            raise ValueError("bad ciphertext")
        return bytes((byte ^ 0xA5) for byte in value[4:])[::-1]


def test_encrypted_store_never_writes_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "protected-secrets.json"
    store = EncryptedSecretStore(path, TestProtector())
    secret = "super-secret-value-12345"
    store.set("elevenlabs_api_key", secret)

    assert store.get("elevenlabs_api_key") == secret
    raw = path.read_text(encoding="utf-8")
    assert secret not in raw
    assert "protected-secrets" not in raw


def test_legacy_env_secret_is_scrubbed_only_after_verified_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = EncryptedSecretStore(tmp_path / "protected-secrets.json", TestProtector())
    monkeypatch.setattr(secret_module, "windows_secret_store", lambda _data_dir: protected)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'JARVIS_ELEVENLABS_API_KEY="legacy-secret-value"\nJARVIS_USER_NAME=Robert\n',
        encoding="utf-8",
    )

    migrated = migrate_legacy_env_secrets(tmp_path, env_file)

    assert migrated == {"elevenlabs_api_key": "legacy-secret-value"}
    assert protected.get("elevenlabs_api_key") == "legacy-secret-value"
    scrubbed = env_file.read_text(encoding="utf-8")
    assert "legacy-secret-value" not in scrubbed
    assert "JARVIS_ELEVENLABS_API_KEY=" in scrubbed
    assert "JARVIS_USER_NAME=Robert" in scrubbed


def test_failed_secret_verification_keeps_legacy_plaintext_for_safe_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingStore:
        def set(self, _name: str, _value: str) -> None:
            return None

        def get(self, _name: str) -> str:
            return "different-value"

    monkeypatch.setattr(secret_module, "windows_secret_store", lambda _data_dir: FailingStore())
    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_AZURE_SPEECH_KEY=must-not-be-lost\n", encoding="utf-8")

    migrated = migrate_legacy_env_secrets(tmp_path, env_file)

    assert migrated == {}
    assert "must-not-be-lost" in env_file.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_real_windows_dpapi_round_trip(tmp_path: Path) -> None:
    protector = DPAPIProtector()
    assert protector.available() is True
    path = tmp_path / "protected-secrets.json"
    store = EncryptedSecretStore(path, protector)
    secret = "runner-windows-dpapi-secret-123"

    store.set("azure_speech_key", secret)

    assert store.get("azure_speech_key") == secret
    assert secret not in path.read_text(encoding="utf-8")
