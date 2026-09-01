from pathlib import Path

from jarvis_papa.actions import ActionQueue


def make_queue(path: Path) -> ActionQueue:
    return ActionQueue(path=path, max_items=20)


def test_action_queue_persists_and_reloads(tmp_path) -> None:
    path = tmp_path / "actions.json"
    queue = make_queue(path)
    card = queue.create(
        title="Assurance",
        summary="Facture demandée",
        source="Assurance",
        importance="high",
        priority_score=80,
        dedupe_key="mail-1",
    )

    reloaded = make_queue(path)
    found = reloaded.get(card.id)
    assert found is not None
    assert found.title == "Assurance"
    assert found.priority_score == 80


def test_duplicate_key_updates_existing_card_instead_of_multiplying(tmp_path) -> None:
    queue = make_queue(tmp_path / "actions.json")
    first = queue.create(
        title="Premier titre",
        summary="Ancien résumé",
        source="Assurance",
        importance="high",
        priority_score=60,
        dedupe_key="same-mail",
    )
    second = queue.create(
        title="Titre mis à jour",
        summary="Nouveau résumé",
        source="Assurance",
        importance="critical",
        priority_score=95,
        dedupe_key="same-mail",
    )

    cards = queue.list(include_snoozed=True)
    assert len(cards) == 1
    assert second.id == first.id
    assert cards[0].title == "Titre mis à jour"
    assert cards[0].priority_score == 95


def test_higher_priority_task_is_shown_first(tmp_path) -> None:
    queue = make_queue(tmp_path / "actions.json")
    queue.create(
        title="Faible",
        summary="Plus tard",
        source="Test",
        importance="normal",
        priority_score=20,
    )
    queue.create(
        title="Urgent",
        summary="À faire maintenant",
        source="Test",
        importance="critical",
        priority_score=95,
    )
    assert queue.list()[0].title == "Urgent"


def test_snooze_hides_task_without_deleting_it(tmp_path) -> None:
    queue = make_queue(tmp_path / "actions.json")
    card = queue.create(
        title="À revoir",
        summary="Document",
        source="Test",
        importance="high",
        priority_score=70,
    )
    assert queue.snooze(card.id, seconds=3600) is True
    assert queue.get(card.id) is not None
    assert all(item.id != card.id for item in queue.list())
    assert any(item.id == card.id for item in queue.list(include_snoozed=True))
