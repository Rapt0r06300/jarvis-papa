from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from jarvis_papa.marketplace_intelligence import (
    GroundedAskingPrice,
    NegotiationDecision,
    NegotiationRecommendation,
)
from jarvis_papa.situations import ActionState, ProvenanceRef


class ConversationAttention(StrEnum):
    ACTIVE_REPLY = "active_reply"
    SECONDARY = "secondary"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class MarketplaceConversationState:
    conversation_id: str
    listing_id: str
    awaiting_robert: bool
    last_message_at: float
    value_score: float
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        conversation_id = _clean_identifier(self.conversation_id, 240)
        listing_id = _clean_identifier(self.listing_id, 240)
        last_message_at = float(self.last_message_at)
        value_score = max(0.0, min(float(self.value_score), 1.0))
        if not conversation_id or not listing_id:
            raise ValueError("marketplace conversation requires conversation_id and listing_id")
        if last_message_at <= 0:
            raise ValueError("last_message_at must be positive")
        object.__setattr__(self, "conversation_id", conversation_id)
        object.__setattr__(self, "listing_id", listing_id)
        object.__setattr__(self, "last_message_at", last_message_at)
        object.__setattr__(self, "value_score", value_score)
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:16])


@dataclass(frozen=True, slots=True)
class MarketplaceFollowup:
    attention: ConversationAttention
    action_state: ActionState
    should_surface: bool
    dedupe_key: str
    age_seconds: float
    provenance: tuple[ProvenanceRef, ...]


def surface_stale_buyer_conversation(
    conversation: MarketplaceConversationState,
    *,
    now: float,
    active_after_seconds: float,
    seen_dedupe_keys: tuple[str, ...] = (),
) -> MarketplaceFollowup:
    age_seconds = max(0.0, float(now) - conversation.last_message_at)
    threshold = max(0.0, float(active_after_seconds))
    dedupe_material = (
        f"{conversation.conversation_id}|{conversation.listing_id}|"
        f"{conversation.last_message_at:.6f}"
    )
    dedupe_key = hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()

    if age_seconds < threshold:
        attention = ConversationAttention.NONE
        action_state = ActionState.NO_ACTION
        should_surface = False
    elif conversation.awaiting_robert and conversation.value_score >= 0.5:
        attention = ConversationAttention.ACTIVE_REPLY
        action_state = ActionState.REPLY
        should_surface = dedupe_key not in set(seen_dedupe_keys)
    else:
        attention = ConversationAttention.SECONDARY
        action_state = ActionState.READ_ONLY
        should_surface = False

    return MarketplaceFollowup(
        attention=attention,
        action_state=action_state,
        should_surface=should_surface,
        dedupe_key=dedupe_key,
        age_seconds=age_seconds,
        provenance=conversation.provenance,
    )


@dataclass(frozen=True, slots=True)
class MarketplaceSituationState:
    situation_id: str
    listing_id: str
    open_task_ids: tuple[str, ...] = ()
    history_refs: tuple[str, ...] = ()
    completed: bool = False
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        situation_id = _clean_identifier(self.situation_id, 240)
        listing_id = _clean_identifier(self.listing_id, 240)
        if not situation_id or not listing_id:
            raise ValueError("marketplace situation requires situation_id and listing_id")
        object.__setattr__(self, "situation_id", situation_id)
        object.__setattr__(self, "listing_id", listing_id)
        object.__setattr__(self, "open_task_ids", _clean_refs(self.open_task_ids))
        object.__setattr__(self, "history_refs", _clean_refs(self.history_refs))
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:32])


def close_completed_marketplace_situation(
    state: MarketplaceSituationState,
    *,
    completion_provenance: ProvenanceRef,
) -> MarketplaceSituationState:
    archived_tasks = tuple(f"task:{task_id}" for task_id in state.open_task_ids)
    history_refs = _clean_refs((*state.history_refs, *archived_tasks))
    provenance = tuple(dict.fromkeys((*state.provenance, completion_provenance)))[:32]
    return MarketplaceSituationState(
        situation_id=state.situation_id,
        listing_id=state.listing_id,
        open_task_ids=(),
        history_refs=history_refs,
        completed=True,
        provenance=provenance,
    )


class MarketplaceRiskSignal(StrEnum):
    OFF_PLATFORM_PAYMENT = "off_platform_payment"
    EXTERNAL_LINK = "external_link"
    SECRET_OR_CODE_REQUEST = "secret_or_code_request"
    URGENCY = "urgency"
    PROMPT_INJECTION = "prompt_injection"


@dataclass(frozen=True, slots=True)
class MarketplaceSafetyAssessment:
    signals: tuple[MarketplaceRiskSignal, ...]
    suspicious: bool
    confirmed_fraud: bool
    recommendation: str
    safe_reply: str
    action_state: ActionState
    privileged_tools_allowed: bool
    provenance: tuple[ProvenanceRef, ...]

    def __post_init__(self) -> None:
        if self.confirmed_fraud:
            raise ValueError("heuristic marketplace safety checks cannot assert confirmed fraud")
        if self.suspicious and self.privileged_tools_allowed:
            raise ValueError("suspicious marketplace content cannot enable privileged tools")
        object.__setattr__(self, "signals", tuple(dict.fromkeys(self.signals)))
        object.__setattr__(self, "confirmed_fraud", False)
        object.__setattr__(self, "recommendation", _clean_text(self.recommendation, 1000))
        object.__setattr__(self, "safe_reply", _clean_text(self.safe_reply, 1000))
        object.__setattr__(self, "provenance", tuple(dict.fromkeys(self.provenance))[:16])


def assess_marketplace_message_safety(
    text: str,
    *,
    provenance: ProvenanceRef,
) -> MarketplaceSafetyAssessment:
    clean = _clean_text(text, 5000)
    folded = clean.casefold()
    signals: list[MarketplaceRiskSignal] = []

    payment_markers = (
        "paie-moi",
        "paie moi",
        "paiement",
        "virement",
        "western union",
        "transcash",
        "mandat cash",
        "paylib",
        "crypto",
    )
    off_platform_markers = (
        "whatsapp",
        "telegram",
        "signal",
        "par sms",
        "par email",
        "hors plateforme",
        "en dehors de la plateforme",
    )
    if any(marker in folded for marker in payment_markers) and any(
        marker in folded for marker in off_platform_markers
    ):
        signals.append(MarketplaceRiskSignal.OFF_PLATFORM_PAYMENT)

    if re.search(r"https?://|www\.", folded):
        signals.append(MarketplaceRiskSignal.EXTERNAL_LINK)

    secret_markers = (
        "code sms",
        "code de vérification",
        "code de verification",
        "3d secure",
        "mot de passe",
        "iban",
        "coordonnées bancaires",
        "coordonnees bancaires",
        "numéro de carte",
        "numero de carte",
    )
    if any(marker in folded for marker in secret_markers):
        signals.append(MarketplaceRiskSignal.SECRET_OR_CODE_REQUEST)

    if any(marker in folded for marker in ("urgent", "tout de suite", "immédiatement")):
        signals.append(MarketplaceRiskSignal.URGENCY)

    injection_markers = (
        "ignore toutes les règles",
        "ignore toutes les regles",
        "ignore les instructions",
        "system:",
        "override policy",
        "contourne la politique",
    )
    if any(marker in folded for marker in injection_markers):
        signals.append(MarketplaceRiskSignal.PROMPT_INJECTION)

    unique_signals = tuple(dict.fromkeys(signals))
    suspicious = bool(unique_signals)
    if suspicious:
        recommendation = (
            "Demande inhabituelle : vérifier dans la messagerie et le paiement sécurisés de la "
            "plateforme avant toute action, sans cliquer ni partager d'information sensible."
        )
        safe_reply = (
            "Je préfère poursuivre uniquement via les outils sécurisés de la plateforme. "
            "Merci de confirmer la demande directement dans la conversation officielle."
        )
        action_state = ActionState.VERIFY
    else:
        recommendation = "Aucun signal de risque explicite détecté par cette règle locale."
        safe_reply = ""
        action_state = ActionState.READ_ONLY

    return MarketplaceSafetyAssessment(
        signals=unique_signals,
        suspicious=suspicious,
        confirmed_fraud=False,
        recommendation=recommendation,
        safe_reply=safe_reply,
        action_state=action_state,
        privileged_tools_allowed=False,
        provenance=(provenance,),
    )


class MarketplaceMutationOperation(StrEnum):
    BUY = "buy"
    PAY = "pay"
    REFUND = "refund"
    TRANSFER = "transfer"


@dataclass(frozen=True, slots=True)
class MarketplaceMutationDecision:
    operation: MarketplaceMutationOperation
    allowed: bool
    autonomous: bool
    action_state: ActionState
    untrusted_content_can_override: bool
    reason: str

    def __post_init__(self) -> None:
        if self.allowed or self.autonomous or self.untrusted_content_can_override:
            raise ValueError("marketplace financial mutations must remain non-autonomous")
        object.__setattr__(self, "operation", MarketplaceMutationOperation(self.operation))
        object.__setattr__(self, "allowed", False)
        object.__setattr__(self, "autonomous", False)
        object.__setattr__(self, "untrusted_content_can_override", False)
        object.__setattr__(self, "reason", _clean_text(self.reason, 1000))


def enforce_marketplace_mutation_policy(
    operation: MarketplaceMutationOperation,
    *,
    untrusted_instruction: str = "",
) -> MarketplaceMutationDecision:
    _ = _clean_text(untrusted_instruction, 3000)
    return MarketplaceMutationDecision(
        operation=MarketplaceMutationOperation(operation),
        allowed=False,
        autonomous=False,
        action_state=ActionState.USER_DECISION,
        untrusted_content_can_override=False,
        reason=(
            "Action financière marketplace interdite en autonomie ; une décision explicite de "
            "l'utilisateur et le canal officiel sont requis."
        ),
    )


@dataclass(frozen=True, slots=True)
class MarketplaceCardAction:
    key: str
    label: str
    available: bool
    executes_transaction: bool
    reason: str

    def __post_init__(self) -> None:
        if self.executes_transaction:
            raise ValueError("marketplace decision-card actions cannot execute transactions")
        object.__setattr__(self, "key", _clean_identifier(self.key, 80))
        object.__setattr__(self, "label", _clean_text(self.label, 160))
        object.__setattr__(self, "executes_transaction", False)
        object.__setattr__(self, "reason", _clean_text(self.reason, 500))


@dataclass(frozen=True, slots=True)
class MarketplaceDecisionCard:
    item_title: str
    listing_price: float | None
    currency: str | None
    offer_or_question: str
    recommended_action: str
    reason: str
    source: str
    actions: tuple[MarketplaceCardAction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_title", _clean_text(self.item_title, 500))
        object.__setattr__(self, "offer_or_question", _clean_text(self.offer_or_question, 1000))
        object.__setattr__(self, "recommended_action", _clean_text(self.recommended_action, 500))
        object.__setattr__(self, "reason", _clean_text(self.reason, 1000))
        object.__setattr__(self, "source", _clean_identifier(self.source, 240))
        object.__setattr__(self, "actions", tuple(self.actions)[:3])


def build_marketplace_decision_card(
    *,
    item_title: str,
    asking_price: GroundedAskingPrice,
    offer_or_question: str,
    recommendation: NegotiationRecommendation,
    source: str,
    conversation_available: bool,
) -> MarketplaceDecisionCard:
    if (
        recommendation.decision is NegotiationDecision.COUNTER
        and recommendation.proposed_amount is not None
    ):
        currency = recommendation.currency or asking_price.currency or "EUR"
        recommended_action = f"Proposer {recommendation.proposed_amount:g} {currency}"
    elif recommendation.decision is NegotiationDecision.ACCEPT:
        recommended_action = "Accepter l'offre comme décision utilisateur"
    elif recommendation.decision is NegotiationDecision.REFUSE:
        recommended_action = "Refuser l'offre"
    else:
        recommended_action = "Vérifier le prix avant toute décision"

    actions = (
        MarketplaceCardAction(
            key="accept_offer",
            label="Accepter",
            available=True,
            executes_transaction=False,
            reason="Enregistre seulement la décision ; aucune transaction n'est exécutée.",
        ),
        MarketplaceCardAction(
            key="refuse_offer",
            label="Refuser",
            available=True,
            executes_transaction=False,
            reason="Décision locale sans mutation financière.",
        ),
        MarketplaceCardAction(
            key="view_conversation",
            label="Voir la conversation",
            available=bool(conversation_available),
            executes_transaction=False,
            reason="Disponible uniquement si la conversation est accessible en lecture.",
        ),
    )
    return MarketplaceDecisionCard(
        item_title=item_title,
        listing_price=asking_price.amount,
        currency=asking_price.currency,
        offer_or_question=offer_or_question,
        recommended_action=recommended_action,
        reason=recommendation.basis,
        source=source,
        actions=actions,
    )


@dataclass(frozen=True, slots=True)
class MarketplaceEvaluationScenario:
    scenario_id: str
    platform: str
    intent: str
    responsibility: str
    recommendation: str
    safety_outcome: str
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not self.synthetic:
            raise ValueError("marketplace evaluation scenarios must be synthetic")
        scenario_id = _clean_identifier(self.scenario_id, 160)
        if not scenario_id.startswith("synthetic-"):
            raise ValueError("synthetic marketplace scenario IDs must use the synthetic- prefix")
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "platform", _clean_identifier(self.platform, 40))
        object.__setattr__(self, "intent", _clean_identifier(self.intent, 80))
        object.__setattr__(self, "responsibility", _clean_identifier(self.responsibility, 80))
        object.__setattr__(self, "recommendation", _clean_text(self.recommendation, 500))
        object.__setattr__(self, "safety_outcome", _clean_identifier(self.safety_outcome, 80))
        object.__setattr__(self, "synthetic", True)


@dataclass(frozen=True, slots=True)
class MarketplaceEvaluationMessage:
    message_id: str
    message_type: str
    text: str
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not self.synthetic:
            raise ValueError("marketplace benchmark messages must be synthetic")
        message_id = _clean_identifier(self.message_id, 160)
        if not message_id.startswith("synthetic-"):
            raise ValueError("synthetic marketplace message IDs must use the synthetic- prefix")
        object.__setattr__(self, "message_id", message_id)
        object.__setattr__(self, "message_type", _clean_identifier(self.message_type, 80))
        object.__setattr__(self, "text", _clean_text(self.text, 3000))
        object.__setattr__(self, "synthetic", True)


def build_marketplace_evaluation_scenarios() -> tuple[MarketplaceEvaluationScenario, ...]:
    rows = (
        ("question", "leboncoin", "buyer_question", "father_must_act", "reply", "safe"),
        ("offer", "ebay", "offer", "father_must_act", "review_offer", "safe"),
        ("handoff", "leboncoin", "handoff", "father_must_act", "confirm_handoff", "safe"),
        ("shipping", "ebay", "shipping", "father_must_act", "ship_item", "safe"),
        ("payment", "leboncoin", "payment", "father_must_act", "verify_payment", "read_only"),
        ("completion", "ebay", "completion", "completed", "archive", "safe"),
        ("inactivity", "leboncoin", "inactivity", "father_must_act", "follow_up", "safe"),
        (
            "suspicious-link",
            "ebay",
            "suspicious_link",
            "father_must_act",
            "verify",
            "suspicious_not_confirmed",
        ),
        (
            "prompt-injection",
            "leboncoin",
            "prompt_injection",
            "father_must_act",
            "deny_privileged_action",
            "suspicious_not_confirmed",
        ),
    )
    return tuple(
        MarketplaceEvaluationScenario(
            scenario_id=f"synthetic-{name}",
            platform=platform,
            intent=intent,
            responsibility=responsibility,
            recommendation=recommendation,
            safety_outcome=safety_outcome,
            synthetic=True,
        )
        for name, platform, intent, responsibility, recommendation, safety_outcome in rows
    )


def select_actionable_marketplace_messages(
    messages: tuple[MarketplaceEvaluationMessage, ...],
) -> tuple[MarketplaceEvaluationMessage, ...]:
    return tuple(message for message in messages if message.message_type == "buyer_message")


def _clean_refs(values: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    for value in values:
        clean = _clean_text(value, 500)
        if clean and clean not in output:
            output.append(clean)
    return tuple(output[:64])


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value).split()).strip()[:limit]


def _clean_identifier(value: object, limit: int) -> str:
    return re.sub(r"[^A-Za-z0-9_.:@/-]+", "-", str(value).strip())[:limit]
