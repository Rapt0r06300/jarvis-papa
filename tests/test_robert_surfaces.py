from __future__ import annotations


def test_p9_01_today_view_surfaces_only_the_few_useful_now_items() -> None:
    from jarvis_papa.robert_surfaces import SurfaceItem, build_today_view

    items = (
        SurfaceItem("bank-verify", "Vérifier un paiement inconnu", "bank", priority=100, requires_decision=True),
        SurfaceItem("parcel-pickup", "Retirer le colis avant demain", "parcel", priority=95, requires_decision=False),
        SurfaceItem("buyer-offer", "Répondre à l'offre de l'acheteur", "marketplace", priority=90, requires_decision=True),
        SurfaceItem("newsletter", "Nouvelle newsletter", "mail", priority=5, requires_decision=False),
        SurfaceItem("promo", "Promotion commerciale", "mail", priority=1, requires_decision=False),
    )
    view = build_today_view(items)

    assert 1 <= len(view.primary_items) <= 3
    assert {item.item_id for item in view.primary_items} == {"bank-verify", "parcel-pickup", "buyer-offer"}
    assert view.technical_diagnostics_visible is False
    assert "newsletter" not in view.briefing.casefold()
    assert "maintenant" in view.briefing.casefold() or "aujourd" in view.briefing.casefold()


def test_p9_02_activity_view_is_event_backed_and_human_readable() -> None:
    from jarvis_papa.robert_surfaces import ActivityEvent, build_activity_view

    events = (
        ActivityEvent("evt-1", "started", "Analyse des nouveaux messages"),
        ActivityEvent("evt-2", "discovery", "Un colis doit être retiré demain"),
        ActivityEvent("evt-3", "completed", "Analyse terminée"),
    )
    view = build_activity_view(events)

    assert view.source_event_ids == ("evt-1", "evt-2", "evt-3")
    assert view.current_text == "Analyse terminée"
    rendered = " ".join(view.lines).casefold()
    for forbidden in ("json", "fastapi", "ollama", "qwen", "localhost", "port 8000"):
        assert forbidden not in rendered


def test_p9_03_decisions_view_centralizes_and_prioritizes_pending_choices() -> None:
    from jarvis_papa.robert_surfaces import DecisionItem, build_decisions_view

    decisions = (
        DecisionItem(
            "doc-approval",
            "Autoriser l'envoi de la facture ?",
            recommendation="Vérifier puis envoyer",
            source="document",
            priority=60,
            delay_cost=20,
        ),
        DecisionItem(
            "buyer-offer",
            "Répondre à l'offre de 75 € ?",
            recommendation="Proposer 90 €",
            source="eBay",
            priority=80,
            delay_cost=30,
        ),
    )
    view = build_decisions_view(decisions)

    assert tuple(item.decision_id for item in view.items) == ("buyer-offer", "doc-approval")
    assert all(item.recommendation for item in view.items)
    assert all(item.source for item in view.items)


def test_p9_04_situations_view_deduplicates_correlated_sources() -> None:
    from jarvis_papa.robert_surfaces import SituationSource, build_situations_view

    sources = (
        SituationSource("order-42", "amazon-42", "Amazon", "Commande expédiée", "Attendre le transporteur", 10),
        SituationSource("order-42", "mondial-42", "Mondial Relay", "Disponible au relais", "Retirer le colis", 20),
        SituationSource("done-1", "mail-old", "Mail", "Terminé", "Aucune action", 1, completed=True),
    )
    view = build_situations_view(sources)

    assert len(view.active) == 1
    assert view.active[0].situation_id == "order-42"
    assert view.active[0].source_names == ("Amazon", "Mondial Relay")
    assert view.active[0].next_step == "Retirer le colis"
    assert len(view.history) == 1


def test_p9_05_unified_search_uses_one_shared_index_and_labels_results() -> None:
    from jarvis_papa.robert_surfaces import SearchRecord, UnifiedSearchIndex

    index = UnifiedSearchIndex(
        (
            SearchRecord("situation", "order-42", "Amazon casque août", "Situation", "Commande casque août"),
            SearchRecord("document", "invoice-42", "facture casque août Amazon", "Fichier local", "Facture casque août"),
            SearchRecord("memory", "pref-1", "réponses courtes acheteurs", "Mémoire", "Préférence de réponse"),
        )
    )
    results = index.search("facture casque août")

    assert {result.record_id for result in results[:2]} >= {"invoice-42"}
    assert all(result.result_type and result.source for result in results)
    assert index.storage_name == "shared-index"
