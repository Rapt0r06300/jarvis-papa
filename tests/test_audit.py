from jarvis_papa.audit import AuditLog


def test_audit_log_redacts_secrets_and_message_bodies(tmp_path) -> None:
    log = AuditLog(path=tmp_path / "audit.jsonl")
    log.record(
        "test",
        action="mail.prepare_reply",
        ok=True,
        metadata={
            "api_key": "secret-key",
            "authorization_token": "secret-token",
            "body": "private mail content",
            "subject": "Facture demandée",
        },
    )

    item = log.recent(1)[0]
    metadata = item["metadata"]
    assert metadata["api_key"] == "[redacted]"
    assert metadata["authorization_token"] == "[redacted]"
    assert metadata["body"] == "[redacted]"
    assert metadata["subject"] == "Facture demandée"
