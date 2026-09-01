from jarvis_papa.security import ActionRisk, SecurityPolicy


def test_read_action_is_allowed_without_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.READ)
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_write_action_is_blocked_without_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.WRITE)
    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.confirmations_remaining == 2


def test_destructive_action_is_blocked_without_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.DESTRUCTIVE)
    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_one_explicit_confirmation_is_not_enough() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.DESTRUCTIVE, confirmed=True)
    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.confirmations_received == 1
    assert decision.confirmations_remaining == 1


def test_sensitive_action_is_allowed_after_two_confirmations() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.DESTRUCTIVE, confirmations=2)
    assert decision.allowed is True
    assert decision.requires_confirmation is True
    assert decision.confirmations_remaining == 0
