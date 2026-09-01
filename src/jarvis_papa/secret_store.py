from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

_SECRET_ENV_FIELDS = {
    "JARVIS_ELEVENLABS_API_KEY": "elevenlabs_api_key",
    "JARVIS_AZURE_SPEECH_KEY": "azure_speech_key",
}
_STORE_VERSION = 1
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class DPAPIProtector:
    """Windows current-user DPAPI protector.

    No LOCAL_MACHINE flag is used: ciphertext is intentionally bound to the
    Windows user profile that protected it. There is no plaintext fallback.
    """

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32" and hasattr(ctypes, "windll")

    def protect(self, value: bytes) -> bytes:
        if not self.available():
            raise RuntimeError("DPAPI is only available on Windows.")
        return self._crypt(value, decrypt=False)

    def unprotect(self, value: bytes) -> bytes:
        if not self.available():
            raise RuntimeError("DPAPI is only available on Windows.")
        return self._crypt(value, decrypt=True)

    @staticmethod
    def _input_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(value, len(value))
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        return _DataBlob(len(value), pointer), buffer

    def _crypt(self, value: bytes, *, decrypt: bool) -> bytes:
        input_blob, input_buffer = self._input_blob(value)
        _ = input_buffer
        output_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if decrypt:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(input_blob),
                None,
                None,
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        else:
            ok = crypt32.CryptProtectData(
                ctypes.byref(input_blob),
                "Jarvis Papa",
                None,
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        if not ok:
            error = ctypes.get_last_error()
            raise OSError(error, "Windows DPAPI operation failed")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            if output_blob.pbData:
                kernel32.LocalFree(output_blob.pbData)


class EncryptedSecretStore:
    """Tiny encrypted key/value file backed by an explicit protector."""

    def __init__(self, path: Path, protector: SecretProtector) -> None:
        self.path = path
        self.protector = protector

    def get(self, name: str) -> str:
        encoded = self._items().get(name)
        if not encoded:
            return ""
        try:
            encrypted = base64.b64decode(encoded.encode("ascii"), validate=True)
            clear = self.protector.unprotect(encrypted)
            return clear.decode("utf-8")
        except (ValueError, UnicodeDecodeError, OSError, RuntimeError):
            return ""

    def set(self, name: str, value: str) -> None:
        name = self._validate_name(name)
        clear = value.strip()
        if not clear:
            self.delete(name)
            return
        encrypted = self.protector.protect(clear.encode("utf-8"))
        items = self._items()
        items[name] = base64.b64encode(encrypted).decode("ascii")
        self._write(items)

    def delete(self, name: str) -> None:
        name = self._validate_name(name)
        items = self._items()
        if name not in items:
            return
        items.pop(name, None)
        self._write(items)

    def get_all(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for name in self._items():
            value = self.get(name)
            if value:
                values[name] = value
        return values

    def _items(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("version") != _STORE_VERSION:
            return {}
        raw = payload.get("items")
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def _write(self, items: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"version": _STORE_VERSION, "items": items}
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @staticmethod
    def _validate_name(name: str) -> str:
        clean = "".join(char for char in name if char.isalnum() or char in {"_", "-"})[:80]
        if clean != name or not clean:
            raise ValueError("Invalid secret name")
        return clean


def windows_secret_store(data_dir: Path) -> EncryptedSecretStore | None:
    protector = DPAPIProtector()
    if not protector.available():
        return None
    return EncryptedSecretStore(data_dir / "protected-secrets.json", protector)


def load_windows_secret_overrides(data_dir: Path) -> dict[str, str]:
    store = windows_secret_store(data_dir)
    if store is None:
        return {}
    overrides: dict[str, str] = {}
    for environment_name, field_name in _SECRET_ENV_FIELDS.items():
        if os.environ.get(environment_name):
            continue
        protected = store.get(field_name)
        if protected:
            overrides[field_name] = protected
    return overrides


def migrate_legacy_env_secrets(data_dir: Path, env_file: Path) -> dict[str, str]:
    """Protect legacy .env secrets and scrub plaintext only after read-back verification."""

    store = windows_secret_store(data_dir)
    if store is None or not env_file.is_file():
        return {}
    try:
        original_lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    migrated: dict[str, str] = {}
    replacements: dict[int, str] = {}
    for index, line in enumerate(original_lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        raw_name, raw_value = line.split("=", 1)
        environment_name = raw_name.strip()
        field_name = _SECRET_ENV_FIELDS.get(environment_name)
        if field_name is None:
            continue
        value = _dotenv_value(raw_value)
        if not value:
            continue
        try:
            store.set(field_name, value)
        except (OSError, RuntimeError, ValueError):
            continue
        if store.get(field_name) != value:
            continue
        migrated[field_name] = value
        replacements[index] = f"{environment_name}="

    if not replacements:
        return migrated
    scrubbed = list(original_lines)
    for index, replacement in replacements.items():
        scrubbed[index] = replacement
    temporary = env_file.with_suffix(env_file.suffix + ".tmp")
    try:
        temporary.write_text("\n".join(scrubbed) + "\n", encoding="utf-8")
        os.replace(temporary, env_file)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return migrated


def _dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()
