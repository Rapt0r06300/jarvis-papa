from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from email.utils import parseaddr
from enum import StrEnum

from jarvis_papa.mail import IncomingMail, mail_assistant
from jarvis_papa.situations import ActionState, ProvenanceRef, Responsibility


EMAIL_TAXONOMY_VERSION = 1
EMAIL_MEANING_SCHEMA_VERSION = 1


class EmailIntent(StrEnum):
    NORMAL = "normal"
    NOISE = "noise"
    NEWSLETTER = "newsletter"
    ORDER = "order"
    SHIPPING = "shipping"
    DELAY = "delay"
    PICKUP = "pickup"
    REFUND = "refund"
    BANK_SECURITY = "bank_security"
    ADMIN = "admin"
    MARKETPLACE = "marketplace"
    NEGOTIATION = "negotiation"
    ACTION = "action"
    REPLY = "reply"
    DEADLINE = "deadline"
    UNKNOWN_IMPORTANT = "unknown_important"


class ModelStage(StrEnum):
    NONE = "none"
    FAST = "fast"
    STRONG = "strong"


@dataclass(frozen=True, slots=True)
class EmailMessage:
    source_id: str
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: float
    references: tuple[str, ...] = ()
    in_reply_to: str = ""
    platform_thread_id: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    folder: str = "Inbox"
    list_unsubscribe: bool = False
    junk: bool = False
    sender_is_father: bool = False

    def __post_init__(self) -> None:
        source_id = _clean_identifier(self.source_id, 120)
        message_id = _clean_message_id(self.message_id)
        sender = _clean_text(self.sender, 500)
        subject = _clean_text(self.subject, 500)
        body = _clean_text(self.body, 20_000)
        received_at = float(self.received_at)
        if not source_id or not message_id or received_at <= 0:
            raise ValueError("email requires source_id, message_id and positive received_at")
        refs = tuple(
            item for item in (_clean_message_id(value) for value in self.references) if item
        )[:50]
        headers: list[tuple[str, str]] = []
        for key, value in self.headers[:80]:
            clean_key = _clean_identifier(str(key).casefold(), 100)
            clean_value = _clean_text(str(value), 1000)
            if clean_key and clean_value:
                headers.append((clean_key, clean_value))
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "message_id", message_id)
        object.__setattr__(self, "sender", sender)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "received_at", received_at)
        object.__setattr__(self, "references", refs)
        object.__setattr__(self, "in_reply_to", _clean_message_id(self.in_reply_to))
        object.__setattr__(self, "platform_thread_id", _clean_identifier(self.platform_thread_id, 240))
        object.__setattr__(self, "headers", tuple(headers))
        object.__setattr__(self, "folder", _clean_text(self.folder, 160) or "Inbox")

    @property
    def provenance(self) -> ProvenanceRef:
        return ProvenanceRef(
            source="email",
            source_id=self.message_id,
            observed_at=self.received_at,
            locator=f"{self.source_id}:{self.folder}",
            content_hash=_sha256(
                f"{self.sender}\n{self.subject}\n{self.body}".encode()
            ),
        )

    def bounded_context(self, *, max_chars: int = 6000) -> dict[str, object]:
        budget = max(800, min(int(max_chars), 8000))
        body_budget = max(400, budget - 1200)
        return {
            "message_id": self.message_id[:240],
            "sender": self.sender[:500],
            "subject": self.subject[:500],
            "body": self.body[:body_budget],
            "references": list(self.references[-8:]),
            "in_reply_to": self.in_reply_to,
            "sender_is_father": self.sender_is_father,
        }

    def to_incoming_mail(self) -> IncomingMail:
        return IncomingMail(
            message_id=None,
            header_message_id=self.message_id,
            author=self.sender,
            subject=self.subject,
            body=self.body,
            folder=self.folder,
            list_unsubscribe=self.list_unsubscribe or self.has_header("list-unsubscribe"),
            junk=self.junk,
        )

    def has_header(self, name: str) -> bool:
        needle = name.casefold().strip()
        return any(key == needle for key, _value in self.headers)

    def header(self, name: str) -> str:
        needle = name.casefold().strip()
        for key, value in self.headers:
            if key == needle:
                return value
        return ""


@dataclass(frozen=True, slots=True)
class TriageDecision:
    intent: EmailIntent
    action_state: ActionState
    confidence: float
    escalation: ModelStage
    reasons: tuple[str, ...]
    bounded_context: dict[str, object]
    taxonomy_version: int = EMAIL_TAXONOMY_VERSION
    destructive_action_allowed: bool = False

    def __post_init__(self) -> None:
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("triage confidence must be between 0 and 1")
        if self.destructive_action_allowed:
            raise ValueError("email triage may never authorize destructive actions")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "reasons",
            tuple(_clean_text(x, 300) for x in self.reasons if x)[:12],
        )


@dataclass(frozen=True, slots=True)
class StructuredEmailMeaning:
    summary: str
    intent: EmailIntent
    action_state: ActionState
    importance: int
    deadline: str | None
    requested_action: str
    references: tuple[str, ...]
    confidence: float
    provenance: tuple[ProvenanceRef, ...]
    entities: tuple[str, ...] = ()
    related_situation: str = ""
    schema_version: int = EMAIL_MEANING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        summary = _clean_text(self.summary, 1200)
        requested_action = _clean_text(self.requested_action, 800)
        confidence = float(self.confidence)
        importance = int(self.importance)
        if not summary:
            raise ValueError("structured email meaning requires a summary")
        if not 0 <= importance <= 100:
            raise ValueError("importance must be between 0 and 100")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.provenance:
            raise ValueError("structured email meaning requires provenance")
        deadline = normalize_model_deadline(self.deadline)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "requested_action", requested_action)
        object.__setattr__(self, "importance", importance)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "deadline", deadline)
        object.__setattr__(
            self,
            "references",
            tuple(_clean_text(x, 300) for x in self.references if x)[:32],
        )
        object.__setattr__(
            self,
            "entities",
            tuple(_clean_text(x, 300) for x in self.entities if x)[:32],
        )
        object.__setattr__(
            self,
            "related_situation",
            _clean_identifier(self.related_situation, 160),
        )

    @classmethod
    def from_model_payload(
        cls,
        payload: object,
        *,
        provenance: ProvenanceRef,
    ) -> StructuredEmailMeaning:
        if not isinstance(payload, dict):
            raise TypeError("model email meaning must be an object")
        allowed = {
            "summary",
            "intent",
            "action_state",
            "importance",
            "deadline",
            "requested_action",
            "references",
            "confidence",
            "entities",
            "related_situation",
            "schema_version",
        }
        if any(str(key) not in allowed for key in payload):
            raise ValueError("unknown fields in model email meaning")
        try:
            intent = EmailIntent(str(payload["intent"]))
            action_state = ActionState(str(payload["action_state"]))
            summary = str(payload["summary"])
            importance = int(payload["importance"])
            confidence = float(payload["confidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid typed model email meaning") from exc
        references = _string_tuple(payload.get("references", ()))
        entities = _string_tuple(payload.get("entities", ()))
        schema_version = int(
            payload.get("schema_version", EMAIL_MEANING_SCHEMA_VERSION)
        )
        if schema_version != EMAIL_MEANING_SCHEMA_VERSION:
            raise ValueError("unsupported email meaning schema version")
        return cls(
            summary=summary,
            intent=intent,
            action_state=action_state,
            importance=importance,
            deadline=(
                payload.get("deadline")
                if payload.get("deadline") is not None
                else None
            ),
            requested_action=str(payload.get("requested_action") or ""),
            references=references,
            confidence=confidence,
            provenance=(provenance,),
            entities=entities,
            related_situation=str(payload.get("related_situation") or ""),
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "intent": self.intent.value,
            "action_state": self.action_state.value,
            "importance": self.importance,
            "deadline": self.deadline,
            "requested_action": self.requested_action,
            "references": list(self.references),
            "confidence": self.confidence,
            "provenance": [item.to_dict() for item in self.provenance],
            "entities": list(self.entities),
            "related_situation": self.related_situation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ThreadIdentity:
    key: str
    confidence: float
    method: str


@dataclass(slots=True)
class EmailThreadState:
    thread_key: str
    message_ids: list[str] = field(default_factory=list)
    latest_state: str = "new"
    open_question: str = ""
    responsibility: Responsibility = Responsibility.UNCLEAR
    action_state: ActionState = ActionState.NO_ACTION
    commitment: str = ""
    requested_document: str = ""
    deadline: str | None = None
    response_sent: bool = False
    last_message_at: float = 0.0
    evidence: list[ProvenanceRef] = field(default_factory=list)

    def update(self, message: EmailMessage, meaning: StructuredEmailMeaning) -> None:
        if message.message_id in self.message_ids:
            return
        self.message_ids.append(message.message_id)
        self.evidence.append(message.provenance)
        self.evidence = self.evidence[-100:]
        self.last_message_at = max(self.last_message_at, message.received_at)
        self.deadline = meaning.deadline or self.deadline
        if meaning.requested_action:
            self.commitment = meaning.requested_action
        document = _requested_document(message.body)
        if document:
            self.requested_document = document

        question = _extract_question(message.body)
        thank_you_only = _is_resolution_ack(message.body)
        if message.sender_is_father:
            self.response_sent = True
            self.open_question = ""
            self.action_state = ActionState.WAIT_FOR_OTHER_PARTY
            self.responsibility = Responsibility.OTHER_PARTY_MUST_ACT
            self.latest_state = "father_replied"
            return

        if thank_you_only and self.response_sent:
            self.open_question = ""
            self.action_state = ActionState.NO_ACTION
            self.responsibility = Responsibility.COMPLETED
            self.latest_state = "completed"
            return

        self.response_sent = False
        if question:
            self.open_question = question
        self.action_state = meaning.action_state
        if meaning.action_state in {
            ActionState.REPLY,
            ActionState.DOCUMENT_REQUIRED,
            ActionState.PICKUP,
            ActionState.VERIFY,
            ActionState.PAYMENT_REVIEW,
            ActionState.DEADLINE,
            ActionState.USER_DECISION,
            ActionState.FOLLOW_UP,
        }:
            self.responsibility = Responsibility.FATHER_MUST_ACT
            self.latest_state = "father_must_act"
        elif meaning.action_state is ActionState.WAIT_FOR_OTHER_PARTY:
            self.responsibility = Responsibility.OTHER_PARTY_MUST_ACT
            self.latest_state = "waiting_for_other_party"
        else:
            self.responsibility = (
                Responsibility.WAITING if self.open_question else Responsibility.UNCLEAR
            )
            self.latest_state = "informational"

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_key": self.thread_key,
            "message_ids": list(self.message_ids),
            "latest_state": self.latest_state,
            "open_question": self.open_question,
            "responsibility": self.responsibility.value,
            "action_state": self.action_state.value,
            "commitment": self.commitment,
            "requested_document": self.requested_document,
            "deadline": self.deadline,
            "response_sent": self.response_sent,
            "last_message_at": self.last_message_at,
            "evidence": [item.to_dict() for item in self.evidence],
        }


class EmailIntelligence:
    """Read-only cheap-first email understanding with typed escalation boundaries."""

    _intent_terms: tuple[tuple[EmailIntent, tuple[str, ...]], ...] = (
        (
            EmailIntent.PICKUP,
            (
                "point relais",
                "point de retrait",
                "à retirer",
                "a retirer",
                "disponible au relais",
            ),
        ),
        (
            EmailIntent.DELAY,
            ("retard", "delay", "livraison retardée", "livraison retardee"),
        ),
        (
            EmailIntent.SHIPPING,
            ("expédi", "expedie", "tracking", "suivi colis", "en transit", "livraison"),
        ),
        (EmailIntent.REFUND, ("remboursement", "remboursé", "rembourse", "refund")),
        (
            EmailIntent.ORDER,
            ("commande", "order", "confirmation d'achat", "confirmation de commande"),
        ),
        (
            EmailIntent.BANK_SECURITY,
            (
                "banque",
                "carte bancaire",
                "compte bloqué",
                "compte bloque",
                "transaction",
                "fraude",
                "sécurité",
                "securite",
            ),
        ),
        (
            EmailIntent.MARKETPLACE,
            ("leboncoin", "ebay", "acheteur", "vendeur", "annonce"),
        ),
        (
            EmailIntent.NEGOTIATION,
            ("offre", "contre-offre", "contre offre", "prix proposé", "prix propose"),
        ),
        (
            EmailIntent.ADMIN,
            (
                "administration",
                "impôt",
                "impot",
                "assurance",
                "dossier",
                "attestation",
                "mutuelle",
            ),
        ),
    )

    def triage(
        self,
        message: EmailMessage,
        *,
        fast_result: StructuredEmailMeaning | None = None,
    ) -> TriageDecision:
        assessment = mail_assistant.assess(message.to_incoming_mail())
        combined = f"{message.subject}\n{message.body}".casefold()
        intent = self._deterministic_intent(combined, assessment.category)
        action_state = self._action_state(combined, message.sender_is_father, intent)
        reasons = [assessment.reason]

        if message.sender_is_father:
            return TriageDecision(
                intent=intent,
                action_state=ActionState.WAIT_FOR_OTHER_PARTY,
                confidence=max(0.9, assessment.confidence),
                escalation=ModelStage.NONE,
                reasons=(
                    "Message envoyé par Robert : l'autre partie doit maintenant répondre.",
                ),
                bounded_context=message.bounded_context(max_chars=1600),
            )

        deterministic = (
            assessment.category in {"newsletter", "suspicious", "important"}
            or intent not in {EmailIntent.NORMAL, EmailIntent.UNKNOWN_IMPORTANT}
        )
        confidence = assessment.confidence
        if deterministic and confidence >= 0.8:
            return TriageDecision(
                intent=intent,
                action_state=action_state,
                confidence=confidence,
                escalation=ModelStage.NONE,
                reasons=tuple(reasons),
                bounded_context=message.bounded_context(max_chars=1800),
            )

        if fast_result is None:
            return TriageDecision(
                intent=(
                    EmailIntent.UNKNOWN_IMPORTANT
                    if assessment.action_required
                    else intent
                ),
                action_state=action_state,
                confidence=min(confidence, 0.69),
                escalation=ModelStage.FAST,
                reasons=tuple(
                    reasons + ["Classification déterministe insuffisamment sûre."]
                ),
                bounded_context=message.bounded_context(max_chars=3200),
            )

        if fast_result.confidence >= 0.72:
            return TriageDecision(
                intent=fast_result.intent,
                action_state=fast_result.action_state,
                confidence=fast_result.confidence,
                escalation=ModelStage.NONE,
                reasons=("Classification rapide structurée suffisamment sûre.",),
                bounded_context=message.bounded_context(max_chars=1800),
            )
        return TriageDecision(
            intent=fast_result.intent,
            action_state=fast_result.action_state,
            confidence=fast_result.confidence,
            escalation=ModelStage.STRONG,
            reasons=("Le modèle rapide reste incertain ; escalade vers le modèle fort.",),
            bounded_context=message.bounded_context(max_chars=5200),
        )

    def meaning_from_rules(self, message: EmailMessage) -> StructuredEmailMeaning:
        decision = self.triage(message)
        assessment = mail_assistant.assess(message.to_incoming_mail())
        return StructuredEmailMeaning(
            summary=assessment.summary or message.subject or "Message reçu",
            intent=decision.intent,
            action_state=decision.action_state,
            importance=assessment.priority_score,
            deadline=_normalize_rule_deadline(assessment.deadline_text),
            requested_action=(
                assessment.recommended_action if assessment.action_required else ""
            ),
            references=tuple(message.references[-8:]),
            confidence=decision.confidence,
            provenance=(message.provenance,),
        )

    @classmethod
    def _deterministic_intent(cls, combined: str, category: str) -> EmailIntent:
        if category == "newsletter":
            return EmailIntent.NEWSLETTER
        if category == "suspicious":
            return EmailIntent.BANK_SECURITY
        for intent, terms in cls._intent_terms:
            if any(term in combined for term in terms):
                return intent
        if any(
            token in combined
            for token in ("avant le", "au plus tard", "échéance", "echeance")
        ):
            return EmailIntent.DEADLINE
        if any(
            token in combined
            for token in ("répondre", "repondre", "merci de", "veuillez")
        ):
            return EmailIntent.ACTION
        if category == "important":
            return EmailIntent.UNKNOWN_IMPORTANT
        return EmailIntent.NORMAL

    @staticmethod
    def _action_state(
        combined: str,
        sender_is_father: bool,
        intent: EmailIntent,
    ) -> ActionState:
        if sender_is_father:
            return ActionState.WAIT_FOR_OTHER_PARTY
        if intent in {EmailIntent.NEWSLETTER, EmailIntent.NOISE, EmailIntent.NORMAL}:
            return ActionState.NO_ACTION
        if intent is EmailIntent.PICKUP:
            return ActionState.PICKUP
        if intent is EmailIntent.BANK_SECURITY:
            return ActionState.VERIFY
        if intent is EmailIntent.DEADLINE:
            return ActionState.DEADLINE
        if intent is EmailIntent.REFUND:
            return ActionState.READ_ONLY
        if any(
            token in combined
            for token in (
                "pièce jointe",
                "piece jointe",
                "document demandé",
                "document demande",
                "transmettre",
                "fournir",
            )
        ):
            return ActionState.DOCUMENT_REQUIRED
        if "?" in combined or any(
            token in combined for token in ("répondre", "repondre")
        ):
            return ActionState.REPLY
        if intent in {EmailIntent.MARKETPLACE, EmailIntent.NEGOTIATION}:
            return ActionState.USER_DECISION
        return ActionState.FOLLOW_UP


def derive_thread_identity(message: EmailMessage) -> ThreadIdentity:
    if message.platform_thread_id:
        return ThreadIdentity(
            key="platform:"
            + _sha256(message.platform_thread_id.casefold().encode()),
            confidence=1.0,
            method="platform_thread_id",
        )
    if message.references:
        root = message.references[0]
        return ThreadIdentity(
            key="message:" + _sha256(root.casefold().encode()),
            confidence=0.98,
            method="references_root",
        )
    if message.in_reply_to:
        return ThreadIdentity(
            key="message:" + _sha256(message.in_reply_to.casefold().encode()),
            confidence=0.95,
            method="in_reply_to",
        )
    if _looks_like_standard_message_id(message.message_id):
        return ThreadIdentity(
            key="message:" + _sha256(message.message_id.casefold().encode()),
            confidence=0.9,
            method="message_id_root",
        )
    subject = _normalized_subject(message.subject)
    sender_address = parseaddr(message.sender)[1].casefold()
    if subject:
        fallback_material = f"{subject}|{_sender_domain(sender_address)}"
        return ThreadIdentity(
            key="subject:" + _sha256(fallback_material.encode()),
            confidence=0.45,
            method="conservative_subject_domain_fallback",
        )
    return ThreadIdentity(
        key="message:" + _sha256(message.message_id.casefold().encode()),
        confidence=0.7,
        method="generated_message_id_only",
    )


def normalize_model_deadline(raw: object) -> str | None:
    if raw is None or raw == "":
        return None
    value = _clean_text(str(raw), 40)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("model deadline must use YYYY-MM-DD") from exc


def _normalize_rule_deadline(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    match = re.fullmatch(r"([0-3]?\d)[/-]([01]?\d)[/-](\d{2}|\d{4})", value)
    if not match:
        return None
    day_value, month_value, year_value = (int(part) for part in match.groups())
    if year_value < 100:
        year_value += 2000
    try:
        return date(year_value, month_value, day_value).isoformat()
    except ValueError:
        return None


def _extract_question(body: str) -> str:
    text = " ".join(body.split())
    matches = re.findall(r"([^?]{3,300}\?)", text)
    return _clean_text(matches[-1], 300) if matches else ""


def _is_resolution_ack(body: str) -> bool:
    clean = " ".join(body.casefold().split()).strip(" .,!;:-")
    if not clean or "?" in clean:
        return False
    return any(
        clean.startswith(prefix)
        for prefix in (
            "merci",
            "merci beaucoup",
            "bien reçu",
            "bien recu",
            "parfait",
            "c'est noté",
            "c’est noté",
        )
    ) and len(clean) <= 180


def _requested_document(body: str) -> str:
    clean = " ".join(body.split())
    match = re.search(
        r"(?:transmettre|fournir|joindre|envoyer)\s+"
        r"(?:le|la|les|un|une|votre|vos)?\s*([^.!?]{3,120})",
        clean,
        flags=re.IGNORECASE,
    )
    return _clean_text(match.group(1), 120) if match else ""


def _normalized_subject(subject: str) -> str:
    clean = subject.casefold().strip()
    clean = re.sub(r"^(?:(?:re|fw|fwd|tr)\s*:\s*)+", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean[:300]


def _looks_like_standard_message_id(value: str) -> bool:
    clean = value.strip()
    return clean.startswith("<") and clean.endswith(">") and "@" in clean


def _sender_domain(address: str) -> str:
    _local, separator, domain = address.rpartition("@")
    return domain if separator else address


def _clean_message_id(value: str) -> str:
    return " ".join(str(value or "").split()).strip()[:300]


def _clean_identifier(value: str, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _clean_text(value: str, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:limit]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected a list of strings")
    output: list[str] = []
    for item in value[:32]:
        if not isinstance(item, str):
            raise TypeError("expected a list of strings")
        clean = _clean_text(item, 300)
        if clean:
            output.append(clean)
    return tuple(output)


email_intelligence = EmailIntelligence()
