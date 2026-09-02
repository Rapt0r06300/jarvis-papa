from __future__ import annotations

from dataclasses import dataclass

import pytest

from jarvis_papa.runtime_progress import (
    ProgressImportance,
    RunId,
    RuntimeProgressEvent,
    RuntimeProgressType,
    StageId,
)
from jarvis_papa.situations import ProvenanceRef


def _presentation():
    from jarvis_papa import runtime_presentation

    return runtime_presentation


def _evidence(source_id: str = "bank-1") -> ProvenanceRef:
    return ProvenanceRef(
        source="mail",
        source_id=source_id,
        observed_at=1_780_000_000.0,
        locator=f"mail:{source_id}",
        content_hash=(source_id.encode("utf-8").hex() * 64)[:64],
    )


def _event(
    *,
    label: str,
    importance: ProgressImportance,
    event_type: RuntimeProgressType = RuntimeProgressType.DISCOVERY,
    stage: str = "email_triage",
    evidence: tuple[ProvenanceRef, ...] = (),
    timestamp: float = 1_780_000_000.0,
) -> RuntimeProgressEvent:
    return RuntimeProgressEvent.create(
        event_type=event_type,
        run_id=RunId("run-p3c"),
        stage_id=StageId(stage),
        timestamp=timestamp,
        public_label=label,
        importance=importance,
        evidence=evidence,
    )


@dataclass
class _SpeechCall:
    text: str
    importance: str
    dedupe_key: str | None


class _FakeSpeechHandler:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[_SpeechCall] = []

    def __call__(self, speech_event):
        if self.fail:
            raise RuntimeError("synthetic tts failure")
        self.calls.append(
            _SpeechCall(
                text=speech_event.text,
                importance=speech_event.importance.value,
                dedupe_key=speech_event.dedupe_key,
            )
        )
        return True


def test_p3_11_critical_bank_event_preempts_only_with_explicit_priority_evidence() -> None:
    presentation = _presentation()
    speaker = _FakeSpeechHandler()
    coordinator = presentation.RuntimePresentationCoordinator(speech_handler=speaker)

    normal = _event(
        label="Analyse de 300 messages",
        importance=ProgressImportance.NORMAL,
        event_type=RuntimeProgressType.PROGRESS_UPDATE,
        stage="email_triage",
    )
    unsupported_critical = _event(
        label="Alerte bancaire supposée",
        importance=ProgressImportance.CRITICAL,
        stage="bank_security",
    )
    supported_critical = _event(
        label="La banque signale une opération urgente à vérifier",
        importance=ProgressImportance.CRITICAL,
        stage="bank_security",
        evidence=(_evidence(),),
        timestamp=1_780_000_001.0,
    )

    first = coordinator.present(normal, category="mail")
    unsupported = coordinator.present(unsupported_critical, category="bank_security")
    urgent = coordinator.present(supported_critical, category="bank_security")

    assert first.visual_text
    assert first.preempt is False
    assert unsupported.preempt is False
    assert urgent.preempt is True
    assert urgent.spoken is True
    assert speaker.calls[-1].importance == "critical"
    assert coordinator.background_run_interrupted is False


def test_p3_12_newsletter_is_silent_while_pickup_expiry_is_spoken() -> None:
    presentation = _presentation()
    speaker = _FakeSpeechHandler()
    coordinator = presentation.RuntimePresentationCoordinator(speech_handler=speaker)

    newsletter = _event(
        label="Nouvelle newsletter commerciale",
        importance=ProgressImportance.IMPORTANT,
        stage="newsletter",
        evidence=(_evidence("newsletter-1"),),
    )
    pickup = _event(
        label="Le colis doit être retiré aujourd’hui avant 18 h",
        importance=ProgressImportance.IMPORTANT,
        stage="pickup_deadline",
        evidence=(_evidence("pickup-1"),),
        timestamp=1_780_000_002.0,
    )

    quiet = coordinator.present(newsletter, category="newsletter")
    spoken = coordinator.present(pickup, category="pickup_deadline")

    assert quiet.visual_text
    assert quiet.speech_attempted is False
    assert quiet.spoken is False
    assert spoken.speech_attempted is True
    assert spoken.spoken is True
    assert speaker.calls[-1].importance == "high"
    assert len(speaker.calls) == 1


def test_p3_13_equivalent_pickup_burst_is_spoken_once_until_state_changes() -> None:
    presentation = _presentation()
    speaker = _FakeSpeechHandler()
    coordinator = presentation.RuntimePresentationCoordinator(speech_handler=speaker)
    evidence = (_evidence("pickup-burst"),)

    events = [
        _event(
            label="Colis disponible au point relais",
            importance=ProgressImportance.IMPORTANT,
            stage="pickup_ready",
            evidence=evidence,
            timestamp=1_780_000_010.0 + index * 0.1,
        )
        for index in range(5)
    ]
    results = [coordinator.present(event, category="pickup_ready") for event in events]

    assert sum(result.spoken for result in results) == 1
    assert len(speaker.calls) == 1
    assert all(result.visual_text for result in results)

    changed = coordinator.present(
        _event(
            label="Le retrait du colis expire demain à 12 h",
            importance=ProgressImportance.IMPORTANT,
            stage="pickup_ready",
            evidence=evidence,
            timestamp=1_780_000_020.0,
        ),
        category="pickup_ready",
    )
    assert changed.spoken is True
    assert len(speaker.calls) == 2


def test_p3_14_tts_exception_keeps_truthful_visual_update_and_run_success() -> None:
    presentation = _presentation()
    coordinator = presentation.RuntimePresentationCoordinator(
        speech_handler=_FakeSpeechHandler(fail=True)
    )
    event = _event(
        label="Le document demandé a été retrouvé",
        importance=ProgressImportance.IMPORTANT,
        stage="document_search",
        evidence=(_evidence("document-1"),),
    )

    result = coordinator.present(event, category="document")

    assert "document" in result.visual_text.casefold()
    assert result.speech_attempted is True
    assert result.spoken is False
    assert result.presentation_ok is True
    assert result.speech_error == "RuntimeError"


def test_p3_13_higher_priority_mapping_preserves_existing_voice_preemption_contract() -> None:
    presentation = _presentation()

    assert presentation.speech_importance_for(ProgressImportance.SILENT).value == "low"
    assert presentation.speech_importance_for(ProgressImportance.NORMAL).value == "normal"
    assert presentation.speech_importance_for(ProgressImportance.IMPORTANT).value == "high"
    assert presentation.speech_importance_for(ProgressImportance.CRITICAL).value == "critical"


def test_p3c_rejects_untyped_runtime_events() -> None:
    presentation = _presentation()
    coordinator = presentation.RuntimePresentationCoordinator(
        speech_handler=_FakeSpeechHandler()
    )

    with pytest.raises(TypeError):
        coordinator.present({"importance": "critical"})
