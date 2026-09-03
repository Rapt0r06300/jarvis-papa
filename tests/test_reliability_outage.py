from __future__ import annotations


def test_p10_11_duplicate_ingestion_is_idempotent_across_restart() -> None:
    from jarvis_papa.reliability_outage import IdempotentIngestionStore

    store = IdempotentIngestionStore()
    for _ in range(3):
        store.ingest("mail-42", situation_id="s-42", task_id="t-42", action_id="a-42")
    snapshot = store.snapshot()
    resumed = IdempotentIngestionStore.from_snapshot(snapshot)
    resumed.ingest("mail-42", situation_id="s-42", task_id="t-42", action_id="a-42")

    assert resumed.logical_event_count == 1
    assert resumed.situation_ids == ("s-42",)
    assert resumed.task_ids == ("t-42",)
    assert resumed.action_ids == ("a-42",)


def test_p10_12_crash_resume_reaches_same_final_state_without_duplicate_side_effects() -> None:
    from jarvis_papa.reliability_outage import run_checkpointed_analysis

    events = tuple(f"event-{index}" for index in range(500))
    uninterrupted = run_checkpointed_analysis(events)
    interrupted = run_checkpointed_analysis(events, crash_after=250, resume=True)

    assert interrupted.completed == 500
    assert interrupted.final_state_hash == uninterrupted.final_state_hash
    assert interrupted.duplicate_side_effects == 0
    assert interrupted.checkpoint_index >= 250


def test_p10_13_offline_local_capabilities_keep_last_known_external_wording() -> None:
    from jarvis_papa.reliability_outage import offline_capability_report

    report = offline_capability_report(
        local_invoice_found=True,
        cached_parcel_status="Disponible au point relais",
        parcel_age_minutes=45,
        parcel_source="email Mondial Relay",
    )

    assert report.local_search_available is True
    assert report.local_documents_available is True
    assert report.memory_available is True
    assert report.external_status_current is False
    assert "dernière information connue" in report.parcel_label.casefold()
    assert "45" in report.parcel_label
    assert "mondial relay" in report.parcel_label.casefold()


def test_p10_14_marketplace_outage_is_isolated_and_health_is_degraded() -> None:
    from jarvis_papa.reliability_outage import run_source_isolation_case

    result = run_source_isolation_case(failed_source="ebay")

    assert result.global_run_completed is True
    assert result.parcel_analysis_completed is True
    assert result.mail_analysis_completed is True
    assert result.document_analysis_completed is True
    assert result.source_health["ebay"] == "degraded"


def test_p10_15_internet_outage_keeps_local_evidence_with_age_source_and_human_message() -> None:
    from jarvis_papa.reliability_outage import graceful_internet_outage

    result = graceful_internet_outage(
        attempted_capability="relay_hours_refresh",
        cached_value="Code 123456 — retrait avant samedi",
        age_minutes=90,
        source="email source",
    )

    assert result.blocking is False
    assert result.current_web_verification_available is False
    assert result.cached_value.startswith("Code 123456")
    assert result.age_minutes == 90
    assert result.source == "email source"
    assert "internet" in result.message.casefold()
    assert "dernière information connue" in result.message.casefold()
