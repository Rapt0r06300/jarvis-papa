from __future__ import annotations


def test_p9_06_primary_copy_rejects_developer_jargon_but_diagnostics_keep_it() -> None:
    from jarvis_papa.decision_cards import audit_robert_copy

    primary = audit_robert_copy("FastAPI JSON error on port 8000 via Ollama", diagnostic=False)
    diagnostic = audit_robert_copy("FastAPI JSON error on port 8000 via Ollama", diagnostic=True)

    assert primary.allowed is False
    assert {"fastapi", "json", "port", "ollama"}.issubset(set(primary.forbidden_terms))
    assert diagnostic.allowed is True
    assert "FastAPI" in diagnostic.text


def test_p9_07_decision_card_bounds_alternatives_and_explains_recommendation() -> None:
    from jarvis_papa.decision_cards import build_decision_card

    card = build_decision_card(
        title="Offre acheteur",
        recommendation="Proposer 45 €",
        reason="L’offre est proche du prix demandé.",
        alternatives=("Accepter 40 €", "Refuser", "Bloquer l’acheteur"),
    )

    assert card.recommendation == "Proposer 45 €"
    assert card.reason
    assert len(card.alternatives) == 2
    assert card.has_more is True


def test_p9_08_parcel_card_never_invents_qr_or_code_actions() -> None:
    from jarvis_papa.decision_cards import ParcelEvidence, build_parcel_card

    card = build_parcel_card(
        ParcelEvidence(
            parcel_name="Casque audio",
            status="Disponible au relais",
            deadline="vendredi",
            pickup_code="AB12",
            qr_payload=None,
            source_mail_id="mail-42",
        )
    )

    assert "vendredi" in card.reason.lower()
    assert "Afficher le code" in card.actions
    assert "Ouvrir le mail" in card.actions
    assert "Me le rappeler demain" in card.actions
    assert all("QR" not in action for action in card.actions)


def test_p9_09_marketplace_card_is_grounded_and_send_remains_governed() -> None:
    from jarvis_papa.decision_cards import MarketplaceEvidence, build_marketplace_card

    card = build_marketplace_card(
        MarketplaceEvidence(
            item="Radio",
            asking_price=50.0,
            buyer_offer=40.0,
            conversation_id="conv-1",
        )
    )

    assert "Radio" in card.title
    assert card.recommendation == "Proposer 45 €"
    assert card.source_context == "conv-1"
    assert card.external_send_allowed is False


def test_p9_10_bank_card_is_cautious_and_has_no_financial_mutation_action() -> None:
    from jarvis_papa.decision_cards import BankReviewEvidence, build_bank_review_card

    card = build_bank_review_card(
        BankReviewEvidence(
            merchant="MERCHANT X",
            amount=-87.40,
            explanation=None,
            confidence=0.35,
            unusual=True,
        )
    )

    lowered = card.body.lower()
    assert "fraude" not in lowered
    assert "vérifier" in lowered or "verification" in lowered or "vérification" in lowered
    forbidden = {"Virer", "Payer", "Rembourser", "Ajouter un bénéficiaire"}
    assert forbidden.isdisjoint(set(card.actions))
