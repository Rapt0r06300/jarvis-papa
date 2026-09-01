from jarvis_papa import advanced_routes as routes
from jarvis_papa.actions import ActionCard
from jarvis_papa.thunderbird import ThunderbirdCommand


class FakeActionQueue:
    def __init__(self, card: ActionCard) -> None:
        self.card = card
        self.removed: list[str] = []

    def get(self, card_id: str):
        return self.card if card_id == self.card.id else None

    def remove(self, card_id: str) -> bool:
        self.removed.append(card_id)
        return True

    def remove_many(self, card_ids: list[str]) -> int:
        self.removed.extend(card_ids)
        return len(card_ids)

    def add(self, card: ActionCard) -> ActionCard:
        self.card = card
        return card


class FakeThunderbirdQueue:
    def __init__(self, command: ThunderbirdCommand | None = None) -> None:
        self.command = command
        self.enqueued: list[ThunderbirdCommand] = []
        self.last_ack_ok: bool | None = None
        self.last_ack_error: str | None = None

    def get(self, command_id: str):
        if self.command is not None and self.command.id == command_id:
            return self.command
        return None

    def enqueue(self, kind: str, payload=None, *, context=None) -> ThunderbirdCommand:
        command = ThunderbirdCommand(
            id="send-command-1234",
            kind=kind,
            payload=payload or {},
            context=context or {},
        )
        self.command = command
        self.enqueued.append(command)
        return command

    def acknowledge(self, command_id: str, *, ok: bool, error=None, result=None) -> bool:
        if self.command is None or self.command.id != command_id:
            return False
        self.last_ack_ok = ok
        self.last_ack_error = error
        self.command.status = "succeeded" if ok else "failed"
        self.command.error = None if ok else error
        self.command.result = dict(result or {})
        return True


def _card() -> ActionCard:
    return ActionCard(
        id="card-advanced-1234",
        title="Répondre à Alice",
        summary="Réponse préparée",
        source="Thunderbird",
        importance="high",
    )


def _verified_inspect() -> ThunderbirdCommand:
    return ThunderbirdCommand(
        id="inspect-command-1234",
        kind="inspect_compose",
        status="succeeded",
        result={
            "compose_tab_id": 42,
            "compose_digest": "digest-exact-123",
            "recipient_display": "Alice <alice@example.org>",
            "subject": "Dossier demandé",
            "attachment_names": ["dossier.pdf"],
            "verified": True,
        },
    )


def test_send_is_blocked_without_exact_double_authorization(monkeypatch) -> None:
    card = _card()
    inspect = _verified_inspect()
    queue = FakeThunderbirdQueue()
    monkeypatch.setattr(routes, "action_queue", FakeActionQueue(card))
    monkeypatch.setattr(routes, "_command_or_404", lambda _command_id: inspect)
    monkeypatch.setattr(routes, "_consume", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(routes, "thunderbird_commands", queue)

    result = routes.send_prepared_mail(
        card.id,
        routes.SendPreparedRequest(
            inspect_command_id=inspect.id,
            authorization_token="invalid-token",
        ),
    )

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert queue.enqueued == []


def test_authorized_send_queues_only_exact_verified_draft(monkeypatch) -> None:
    card = _card()
    inspect = _verified_inspect()
    queue = FakeThunderbirdQueue()
    monkeypatch.setattr(routes, "action_queue", FakeActionQueue(card))
    monkeypatch.setattr(routes, "_command_or_404", lambda _command_id: inspect)
    monkeypatch.setattr(routes, "_consume", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(routes, "thunderbird_commands", queue)
    monkeypatch.setattr(routes.audit_log, "record", lambda *_args, **_kwargs: None)

    result = routes.send_prepared_mail(
        card.id,
        routes.SendPreparedRequest(
            inspect_command_id=inspect.id,
            authorization_token="authorized-token",
        ),
    )

    assert result["ok"] is True
    assert result["state"] == "partial"
    assert len(queue.enqueued) == 1
    command = queue.enqueued[0]
    assert command.kind == "send_reply"
    assert command.payload["compose_tab_id"] == 42
    assert command.payload["expected_compose_digest"] == "digest-exact-123"


def test_send_ack_without_thunderbird_proof_is_forced_to_failed(monkeypatch) -> None:
    command = ThunderbirdCommand(
        id="send-command-1234",
        kind="send_reply",
        status="pending",
        context={},
    )
    queue = FakeThunderbirdQueue(command)
    monkeypatch.setattr(routes, "thunderbird_commands", queue)
    monkeypatch.setattr(routes.audit_log, "record", lambda *_args, **_kwargs: None)

    result = routes.advanced_thunderbird_ack(
        command.id,
        routes.ThunderbirdAckRequest(
            ok=True,
            result={"verified": True, "mode": "sendNow", "header_message_id": ""},
        ),
    )

    assert result["ok"] is True
    assert queue.last_ack_ok is False
    assert command.status == "failed"
    assert "preuve suffisante" in (queue.last_ack_error or "")


def test_repair_never_runs_without_double_authorization(monkeypatch) -> None:
    called = False

    def forbidden_repair(_components):
        nonlocal called
        called = True
        raise AssertionError("repair must not run")

    monkeypatch.setattr(routes, "_consume", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(routes.repair_service, "repair", forbidden_repair)

    result = routes.repair_execute(
        routes.RepairRequest(
            components=["voice", "thunderbird"],
            authorization_token="invalid",
        )
    )

    assert result["ok"] is False
    assert called is False


def test_browser_mutation_never_runs_without_double_authorization(monkeypatch) -> None:
    called = False

    def forbidden_execute(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("browser mutation must not run")

    monkeypatch.setattr(routes, "_consume", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(routes.browser_workflow, "execute", forbidden_execute)

    result = routes.browser_execute(
        routes.BrowserExecuteRequest(
            url="https://example.org/form",
            fields={"name": "Robert"},
            button_text="Continuer",
            verify_text="Merci",
            authorization_token="invalid",
        )
    )

    assert result["ok"] is False
    assert called is False
