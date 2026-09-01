from jarvis_papa.confirmations import ConfirmationManager


def test_confirmation_manager_requires_two_distinct_steps() -> None:
    manager = ConfirmationManager()
    started = manager.start("mail.prepare_reply", "préparer un brouillon")
    assert started.ok is True
    assert started.challenge_id

    first = manager.confirm(started.challenge_id)
    assert first.ok is True
    assert first.step == 1
    assert first.completed is False
    assert first.authorization_token is None

    second = manager.confirm(started.challenge_id)
    assert second.ok is True
    assert second.step == 2
    assert second.completed is True
    assert second.authorization_token


def test_grant_is_action_bound_and_one_use() -> None:
    manager = ConfirmationManager()
    started = manager.start("memory.remember", "mémoriser une préférence")
    assert started.challenge_id
    manager.confirm(started.challenge_id)
    completed = manager.confirm(started.challenge_id)
    assert completed.authorization_token

    assert manager.consume(completed.authorization_token, "browser.download") is False
    # Wrong action consumed the grant deliberately: it can never be replayed elsewhere.
    assert manager.consume(completed.authorization_token, "memory.remember") is False


def test_correct_grant_can_be_consumed_only_once() -> None:
    manager = ConfirmationManager()
    started = manager.start("actions.snooze", "remettre la tâche à plus tard")
    assert started.challenge_id
    manager.confirm(started.challenge_id)
    completed = manager.confirm(started.challenge_id)
    assert completed.authorization_token

    assert manager.consume(completed.authorization_token, "actions.snooze") is True
    assert manager.consume(completed.authorization_token, "actions.snooze") is False


def test_expired_challenge_is_rejected(monkeypatch) -> None:
    manager = ConfirmationManager(challenge_ttl_seconds=1)
    now = 1000.0
    monkeypatch.setattr("jarvis_papa.confirmations.time.time", lambda: now)
    started = manager.start("x", "description")
    assert started.challenge_id
    monkeypatch.setattr("jarvis_papa.confirmations.time.time", lambda: now + 2.0)
    result = manager.confirm(started.challenge_id)
    assert result.ok is False
