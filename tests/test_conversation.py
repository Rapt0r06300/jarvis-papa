from __future__ import annotations

from jarvis_papa.agent import AgentResult
from jarvis_papa.conversation import ConversationManager


def test_conversation_preserves_client_ids_and_context_route(monkeypatch) -> None:
    manager = ConversationManager()
    calls: list[dict[str, object]] = []

    def fake_run(prompt: str, **kwargs) -> AgentResult:
        calls.append({"prompt": prompt, **kwargs})
        route = str(kwargs.get("route") or "knowledge")
        observations = (
            {
                "tool": "pending_actions",
                "state": "success",
                "actions": [
                    {"ordinal": 1, "card_id": "mail-1", "title": "Banque"},
                    {"ordinal": 2, "card_id": "mail-2", "title": "Assurance"},
                ],
            },
        )
        return AgentResult(
            True,
            "Réponse de test.",
            ("pending_actions",),
            route,
            "deterministic",
            observations,
            0,
            "success",
        )

    monkeypatch.setattr("jarvis_papa.conversation.jarvis_agent.run", fake_run)
    conversation_id = "conversation-test-0001"
    first_request = "request-test-0001"
    first = manager.turn(
        "Quels sont mes mails importants ?",
        conversation_id=conversation_id,
        request_id=first_request,
    )
    assert first.conversation_id == conversation_id
    assert first.request_id == first_request
    assert first.route == "mail"

    second = manager.turn(
        "Ouvre le deuxième.",
        conversation_id=conversation_id,
        request_id="request-test-0002",
    )
    assert second.route == "mail"
    assert calls[-1]["conversation_context"]
    assert calls[-1]["history"]


def test_cancel_rejects_unknown_or_finished_request(monkeypatch) -> None:
    manager = ConversationManager()

    def fake_run(prompt: str, **kwargs) -> AgentResult:
        return AgentResult(True, "Terminé.", route=str(kwargs.get("route") or "knowledge"))

    monkeypatch.setattr("jarvis_papa.conversation.jarvis_agent.run", fake_run)
    conversation_id = "conversation-test-0002"
    request_id = "request-test-0003"
    manager.turn("Bonjour", conversation_id=conversation_id, request_id=request_id)

    assert manager.cancel(conversation_id, request_id) is False
    assert manager.cancel(conversation_id, "request-inconnu-0004") is False
    assert manager.reset(conversation_id) is True


def test_invalid_external_ids_are_not_reused(monkeypatch) -> None:
    manager = ConversationManager()

    def fake_run(prompt: str, **kwargs) -> AgentResult:
        return AgentResult(True, "Bonjour.", route=str(kwargs.get("route") or "knowledge"))

    monkeypatch.setattr("jarvis_papa.conversation.jarvis_agent.run", fake_run)
    turn = manager.turn("Bonjour", conversation_id="../bad", request_id="x")
    assert turn.conversation_id != "../bad"
    assert turn.request_id != "x"
    assert len(turn.conversation_id) >= 8
    assert len(turn.request_id) >= 8
