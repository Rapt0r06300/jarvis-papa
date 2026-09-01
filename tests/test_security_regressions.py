from fastapi.testclient import TestClient

import jarvis_papa.routes as routes_module
from jarvis_papa.actions import ActionKind, ActionOption
from jarvis_papa.app import app
from jarvis_papa.dashboard_secure import dashboard_html
from jarvis_papa.thunderbird import ThunderbirdCommandQueue

client = TestClient(app)


def test_non_read_action_options_fail_closed() -> None:
    send = ActionOption(
        id="send",
        label="Envoyer",
        kind=ActionKind.SEND_REPLY,
        requires_confirmation=False,
    )
    dismiss = ActionOption(
        id="dismiss",
        label="Plus tard",
        kind=ActionKind.DISMISS,
        requires_confirmation=False,
    )
    read = ActionOption(
        id="open",
        label="Ouvrir",
        kind=ActionKind.OPEN_EMAIL,
        requires_confirmation=False,
    )

    assert send.requires_confirmation is True
    assert dismiss.requires_confirmation is True
    assert read.requires_confirmation is False


def test_thunderbird_mutation_success_requires_verified_proof(tmp_path) -> None:
    queue = ThunderbirdCommandQueue(path=tmp_path / "commands.json")
    command = queue.enqueue("prepare_reply", {"message_id": 1})

    assert queue.acknowledge(command.id, ok=True) is False
    assert queue.get(command.id).status == "pending"

    assert queue.acknowledge(command.id, ok=True, result={"verified": True}) is True
    stored = queue.get(command.id)
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.result["verified"] is True


def test_legacy_ack_cannot_fake_mutation_success(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_LOCAL_API_TOKEN", raising=False)
    queue = ThunderbirdCommandQueue(path=tmp_path / "commands.json")
    command = queue.enqueue("sort_newsletters", {"items": []})
    monkeypatch.setattr(routes_module, "thunderbird_commands", queue)

    response = client.post(
        f"/api/thunderbird/commands/{command.id}/ack",
        json={"ok": True},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert queue.get(command.id).status == "pending"


def test_legacy_dashboard_uses_exact_bindings_and_verified_send() -> None:
    html = dashboard_html()

    assert "description: actionText, binding" in html
    assert "{card_id: card.id, option_id: option.id}" in html
    assert "{card_id: card.id, hours}" in html
    assert "{card_id: card.id, paths}" in html
    assert "{card_ids: cardIds}" in html
    assert "/send/inspect" in html
    assert "/send/plan/" in html
    assert "proof.verified !== true" in html
    assert "proof.mode !== 'sendNow'" in html
