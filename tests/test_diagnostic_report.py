from __future__ import annotations

import json
import zipfile
from pathlib import Path

from jarvis_papa.diagnostic_report import export_report, redact


def test_redact_masks_tokens_passwords_and_private_paths(monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Robert\AppData\Local")
    payload = {
        "token": "secret-token-value",
        "nested": {
            "password": "SuperSecret",
            "safe": "sk-this-is-a-long-secret-token-123456789",
            "path": r"C:\Users\Robert\AppData\Local\JarvisPapa\runtime",
        },
    }
    redacted = redact(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)
    assert "secret-token-value" not in serialized
    assert "SuperSecret" not in serialized
    assert "sk-this-is" not in serialized
    assert "[REDACTED]" in serialized


def test_export_report_creates_minimal_privacy_safe_zip(tmp_path: Path) -> None:
    destination = tmp_path / "Rapport-Jarvis.zip"
    path = export_report(destination)
    assert path == destination.resolve()
    assert path.is_file()
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {"diagnostic.json", "LISEZ-MOI.txt"}
        payload = json.loads(archive.read("diagnostic.json").decode("utf-8"))
        readme = archive.read("LISEZ-MOI.txt").decode("utf-8")
    assert payload["product"]["name"] == "Jarvis Papa"
    assert "diagnostics" in payload
    assert "memory" in payload
    assert "storage" in payload
    assert "Aucun contenu de mail" in readme
