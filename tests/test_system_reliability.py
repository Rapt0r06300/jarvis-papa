import zipfile
from pathlib import Path

from jarvis_papa.system_reliability import BackupManager, SessionRecovery, WindowsStartupManager


def test_backup_round_trip(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    memory = runtime / "jarvis_memory.sqlite3"
    memory.write_bytes(b"memory-state")
    (runtime / "jarvis-desktop.log").write_text("ignore me", encoding="utf-8")
    (tmp_path / "protected-secrets.json").write_text('{"version": 1}', encoding="utf-8")

    manager = BackupManager(tmp_path, runtime)
    created = manager.create("test")

    assert created.ok is True
    assert created.files == 2
    memory.write_bytes(b"changed")

    restored = manager.restore(Path(created.path))

    assert restored.ok is True
    assert memory.read_bytes() == b"memory-state"


def test_backup_excludes_operational_security_state(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    updates = runtime / "updates"
    updates.mkdir(parents=True)
    (runtime / "jarvis_memory.sqlite3").write_bytes(b"memory")
    (runtime / "kill-switch.json").write_text('{"active": true}', encoding="utf-8")
    (runtime / "circuit-breakers.json").write_text("{}", encoding="utf-8")
    (runtime / "desktop-session-active.json").write_text("{}", encoding="utf-8")
    (runtime / "audit.jsonl").write_text("audit\n", encoding="utf-8")
    (updates / "update-state.json").write_text("{}", encoding="utf-8")

    created = BackupManager(tmp_path, runtime).create("security")

    assert created.ok is True
    with zipfile.ZipFile(created.path) as archive:
        names = set(archive.namelist())
    assert "runtime/jarvis_memory.sqlite3" in names
    assert "runtime/kill-switch.json" not in names
    assert "runtime/circuit-breakers.json" not in names
    assert "runtime/desktop-session-active.json" not in names
    assert "runtime/audit.jsonl" not in names
    assert "runtime/updates/update-state.json" not in names


def test_backup_rejects_path_traversal(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.txt", "nope")

    result = BackupManager(tmp_path, runtime).restore(archive)

    assert result.ok is False
    assert not (tmp_path.parent / "outside.txt").exists()


def test_session_recovery_detects_unclean_previous_run(tmp_path: Path) -> None:
    recovery = SessionRecovery(tmp_path)

    first = recovery.begin()
    second = recovery.begin()

    assert first["previous_unclean"] is False
    assert second["previous_unclean"] is True
    assert recovery.report.is_file()

    recovery.end()
    assert not recovery.marker.exists()


def test_startup_command_is_deterministic() -> None:
    command = WindowsStartupManager().command()

    assert command
    assert "python" in command.casefold() or command.casefold().endswith(".exe")
