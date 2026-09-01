import json
import struct
import sys
import threading
import urllib.error
import urllib.request
from typing import Any

from jarvis_papa.config import settings


_write_lock = threading.Lock()


def _api_url(path: str) -> str:
    return f"http://{settings.host}:{settings.port}{path}"


def _api_request(
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, Any] | list[Any] | None:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        _api_url(path),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError):
        return None

    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def read_message() -> dict[str, Any] | None:
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) != 4:
        return None
    (length,) = struct.unpack("<I", raw_length)
    if length <= 0 or length > 8 * 1024 * 1024:
        return None

    raw = sys.stdin.buffer.read(length)
    if len(raw) != length:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def send_message(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = struct.pack("<I", len(encoded))
    with _write_lock:
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()


def _poll_commands(stop_event: threading.Event) -> None:
    sent: set[str] = set()
    while not stop_event.wait(2):
        payload = _api_request("GET", "/api/thunderbird/commands")
        if not isinstance(payload, list):
            continue

        for item in payload:
            if not isinstance(item, dict):
                continue
            command_id = item.get("id")
            if not isinstance(command_id, str) or command_id in sent:
                continue
            sent.add(command_id)
            send_message({"type": "command", "command": item})


def _handle_message(message: dict[str, Any]) -> None:
    message_type = message.get("type")

    if message_type == "ping":
        send_message({"type": "pong"})
        return

    if message_type == "new_mail":
        mail = message.get("mail")
        if not isinstance(mail, dict):
            send_message({"type": "error", "error": "invalid_mail_payload"})
            return
        result = _api_request("POST", "/api/mail/incoming", mail)
        send_message({"type": "mail_ack", "result": result or {"accepted": False}})
        return

    if message_type == "command_ack":
        command_id = message.get("command_id")
        if not isinstance(command_id, str):
            return
        _api_request("POST", f"/api/thunderbird/commands/{command_id}/ack", {})
        return

    send_message({"type": "error", "error": "unknown_message_type"})


def run() -> None:
    stop_event = threading.Event()
    poller = threading.Thread(target=_poll_commands, args=(stop_event,), daemon=True)
    poller.start()
    try:
        while True:
            message = read_message()
            if message is None:
                break
            _handle_message(message)
    finally:
        stop_event.set()
        poller.join(timeout=1)


if __name__ == "__main__":
    run()
