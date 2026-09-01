from dataclasses import asdict, dataclass, field
from threading import Lock
from uuid import uuid4


@dataclass(slots=True)
class ThunderbirdCommand:
    id: str
    kind: str
    payload: dict[str, object] = field(default_factory=dict)
    acknowledged: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ThunderbirdCommandQueue:
    def __init__(self) -> None:
        self._commands: list[ThunderbirdCommand] = []
        self._lock = Lock()

    def enqueue(self, kind: str, payload: dict[str, object] | None = None) -> ThunderbirdCommand:
        command = ThunderbirdCommand(
            id=uuid4().hex,
            kind=kind,
            payload=payload or {},
        )
        with self._lock:
            self._commands.append(command)
        return command

    def pending(self) -> list[ThunderbirdCommand]:
        with self._lock:
            return [command for command in self._commands if not command.acknowledged]

    def acknowledge(self, command_id: str) -> bool:
        with self._lock:
            for command in self._commands:
                if command.id == command_id:
                    command.acknowledged = True
                    return True
        return False


thunderbird_commands = ThunderbirdCommandQueue()
