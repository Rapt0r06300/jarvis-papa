from jarvis_papa.security import ActionRisk, SecurityPolicy


def test_read_action_is_allowed_without_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.READ)
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_write_action_is_blocked_without_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.WRITE)
    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_destructive_action_is_blocked_without_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.DESTRUCTIVE)
    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_sensitive_action_is_allowed_after_explicit_confirmation() -> None:
    decision = SecurityPolicy().evaluate(ActionRisk.DESTRUCTIVE, confirmed=True)
    assert decision.allowed is True
    assert decision.requires_confirmation is True
