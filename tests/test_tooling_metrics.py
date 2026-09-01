from __future__ import annotations

from jarvis_papa import tooling
from jarvis_papa.tooling import ToolRegistry, ToolRisk, ToolSpec, ToolState


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def record(self, name: str, **kwargs: object) -> None:
        self.calls.append((name, dict(kwargs)))


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        category="test",
        description="test",
        risk=ToolRisk.SAFE,
        read_only=True,
        timeout_seconds=1.0,
        parameters={
            "type": "object",
            "properties": {"secret": {"type": "string"}},
            "required": ["secret"],
            "additionalProperties": False,
        },
    )


def test_tool_metrics_do_not_record_arguments(monkeypatch) -> None:
    recorder = Recorder()
    monkeypatch.setattr(tooling, "local_metrics", recorder)
    registry = ToolRegistry()
    registry.register(
        _spec("demo"),
        lambda arguments: {"ok": True, "detail": f"used {arguments['secret']}"},
    )

    result = registry.execute("demo", {"secret": "TOP-SECRET-ARGUMENT"})

    assert result.state is ToolState.SUCCESS
    assert len(recorder.calls) == 1
    name, payload = recorder.calls[0]
    assert name == "tool.demo"
    assert payload["ok"] is True
    assert payload["final_state"] == "success"
    serialized = repr(recorder.calls)
    assert "TOP-SECRET-ARGUMENT" not in serialized


def test_partial_tool_is_not_counted_as_failure(monkeypatch) -> None:
    recorder = Recorder()
    monkeypatch.setattr(tooling, "local_metrics", recorder)
    registry = ToolRegistry()
    registry.register(
        _spec("queued"),
        lambda _arguments: {"ok": True, "state": "partial", "detail": "queued"},
    )

    result = registry.execute("queued", {"secret": "ignored"})

    assert result.state is ToolState.PARTIAL
    assert recorder.calls[0][1]["ok"] is True
    assert recorder.calls[0][1]["final_state"] == "partial"


def test_failed_tool_is_recorded_without_error_payload(monkeypatch) -> None:
    recorder = Recorder()
    monkeypatch.setattr(tooling, "local_metrics", recorder)
    registry = ToolRegistry()
    registry.register(
        _spec("broken"),
        lambda _arguments: (_ for _ in ()).throw(RuntimeError("SECRET-IN-ERROR")),
    )

    result = registry.execute("broken", {"secret": "OTHER-SECRET"})

    assert result.state is ToolState.FAILED
    name, payload = recorder.calls[0]
    assert name == "tool.broken"
    assert payload["ok"] is False
    assert payload["final_state"] == "failed"
    serialized = repr(recorder.calls)
    assert "SECRET-IN-ERROR" not in serialized
    assert "OTHER-SECRET" not in serialized
