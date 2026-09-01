from jarvis_papa.browser_workflow import BrowserWorkflow


class FakeGuard:
    available = True

    @staticmethod
    def _validate_public_url(raw_url: str) -> str:
        if raw_url.startswith("http://127."):
            raise ValueError("Adresse locale refusée")
        return raw_url


def test_browser_workflow_rejects_password_and_financial_fields() -> None:
    workflow = BrowserWorkflow()
    workflow._guard = FakeGuard()

    password = workflow.execute(
        raw_url="https://example.org/login",
        fields={"password": "secret-value"},
        button_text="Connexion",
    )
    card = workflow.execute(
        raw_url="https://example.org/pay",
        fields={"card_number": "4111111111111111"},
        button_text="Payer",
    )

    assert password["ok"] is False
    assert card["ok"] is False
    assert "refuse" in str(password["detail"]).casefold()


def test_browser_workflow_keeps_ssrf_guard_before_any_navigation() -> None:
    workflow = BrowserWorkflow()
    workflow._guard = FakeGuard()

    result = workflow.execute(
        raw_url="http://127.0.0.1/admin",
        fields={},
        button_text="Continuer",
    )

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert "locale" in str(result["detail"]).casefold()


def test_long_voice_style_text_is_not_relevant_to_browser_guard() -> None:
    workflow = BrowserWorkflow()
    workflow._guard = FakeGuard()
    result = workflow.execute(
        raw_url="https://example.org/form",
        fields={"comment": "mot de passe"},
        button_text="Envoyer",
    )

    assert result["ok"] is False
