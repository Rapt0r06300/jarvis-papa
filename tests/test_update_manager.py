from pathlib import Path

import pytest

from jarvis_papa.update_manager import UpdateManager


def test_update_manifest_requires_complete_fields(tmp_path: Path) -> None:
    manager = UpdateManager(tmp_path, current_version="1.2.3")

    manifest = manager._parse_manifest(
        {
            "version": "1.3.0",
            "installer_url": "https://updates.example.test/JarvisPapa-Setup.exe",
            "sha256": "a" * 64,
        }
    )

    assert manifest.version == "1.3.0"
    assert manifest.sha256 == "a" * 64


def test_update_version_comparison_is_numeric(tmp_path: Path) -> None:
    manager = UpdateManager(tmp_path, current_version="1.9.9")

    assert manager._version_tuple("v1.10.0") > manager._version_tuple("1.9.9")


def test_update_rejects_non_https_channel(tmp_path: Path) -> None:
    manager = UpdateManager(tmp_path)

    result = manager.check("http://updates.example.test/manifest.json")

    assert result["ok"] is False
    assert "HTTPS" in str(result["detail"])


def test_update_manifest_rejects_invalid_version(tmp_path: Path) -> None:
    manager = UpdateManager(tmp_path)

    with pytest.raises(ValueError):
        manager._version_tuple("release-next")
