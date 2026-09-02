from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from jarvis_papa.commitments import commitment_extractor
from jarvis_papa.email_intelligence import (
    EmailIntent,
    EmailMessage,
    EmailThreadState,
    StructuredEmailMeaning,
    TriageDecision,
)
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import ActionState, ProvenanceRef, Responsibility

_PARIS = ZoneInfo("Europe/Paris")
_WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


@dataclass(frozen=True, slots=True)
class EmailCommitment:
    actor: str
    obligation: str
    due_date: str | None
    source_wording: str
    confidence: float
    provenance: ProvenanceRef

    def __post_init__(self) -> None:
        actor = self.actor.strip().casefold()
        obligation = " ".join(self.obligation.split()).strip(" ,;:-")[:500]
        wording = " ".join(self.source_wording.split()).strip()[:200]
        confidence = float(self.confidence)
        if actor not in {"father", "other_party", "unknown"}:
            raise ValueError("unsupported commitment actor")
        if not obligation:
            raise ValueError("commitment requires an obligation")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("commitment confidence must be between 0 and 1")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "obligation", obligation)
        object.__setattr__(self, "source_wording", wording)
        object.__setattr__(self, "confidence", confidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "actor": self.actor,
            "obligation": self.obligation,
            "due_date": self.due_date,
            "source_wording": self.source_wording,
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict(),
        }


def extract_email_commitments(
    message: EmailMessage,
    meaning: StructuredEmailMeaning | None = None,
) -> tuple[EmailCommitment, ...]:
    """Reuse the existing detector and add actor/date normalization."""
    output: list[EmailCommitment] = []
    detected = commitment_extractor.detect(
        message.body,
        source_hint=f"email:{message.message_id}",
    )
    for item in detected:
        wording = _deadline_source_wording(message.body, item.deadline)
        output.append(
            EmailCommitment(
                actor="father",
                obligation=item.action,
                due_date=_normalize_deadline(item.deadline or wording, message.received_at),
                source_wording=wording,
                confidence=item.confidence,
                provenance=message.provenance,
            )
        )

    promise = _future_father_promise(message)
    if promise is not None:
        obligation, wording, due_date = promise
        output.append(
            EmailCommitment(
                actor="father",
                obligation=obligation,
                due_date=due_date,
                source_wording=wording,
                confidence=0.88,
                provenance=message.provenance,
            )
        )

    if meaning is not None and meaning.requested_action:
        key = meaning.requested_action.casefold()
        if not any(item.obligation.casefold() == key for item in output):
            output.append(
                EmailCommitment(
                    actor="father",
                    obligation=meaning.requested_action,
                    due_date=meaning.deadline,
                    source_wording=_deadline_source_wording(message.body, None),
                    confidence=max(0.55, meaning.confidence),
                    provenance=message.provenance,
                )
            )

    deduped: list[EmailCommitment] = []
    seen: set[tuple[str, str, str | None]] = set()
    for item in output:
        key = (item.actor, item.obligation.casefold(), item.due_date)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(deduped[:8])


@dataclass(slots=True)
class RuntimeEmailThreadState(EmailThreadState):
    commitments: list[EmailCommitment] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    def update(self, message: EmailMessage, meaning: StructuredEmailMeaning) -> None:
        if message.message_id in self.message_ids:
            return
        EmailThreadState.update(self, message, meaning)
        for entity in meaning.entities:
            if entity not in self.entities:
                self.entities.append(entity)
        self.entities = self.entities[-100:]

        new_commitments = extract_email_commitments(message, meaning)
        for item in new_commitments:
            duplicate = any(
                existing.actor == item.actor
                and existing.obligation.casefold() == item.obligation.casefold()
                and existing.due_date == item.due_date
                for existing in self.commitments
            )
            if not duplicate:
                self.commitments.append(item)
        self.commitments = self.commitments[-50:]
        if new_commitments:
            latest = new_commitments[-1]
            self.commitment = latest.obligation
            if latest.due_date:
                self.deadline = latest.due_date

        father_future = message.sender_is_father and bool(new_commitments) and _looks_future_promise(
            message.body
        )
        if father_future:
            self.action_state = (
                ActionState.DEADLINE
                if any(item.due_date for item in new_commitments)
                else ActionState.FOLLOW_UP
            )
            self.responsibility = Responsibility.FATHER_MUST_ACT
            self.latest_state = "father_committed"

    def to_situation_payload(self) -> dict[str, object]:
        return {
            "thread_key": self.thread_key,
            "latest_state": self.latest_state,
            "open_question": self.open_question,
            "responsibility": self.responsibility.value,
            "action_state": self.action_state.value,
            "commitments": [item.to_dict() for item in self.commitments],
            "requested_document": self.requested_document,
            "deadline": self.deadline,
            "entities": list(self.entities),
            "evidence": [item.to_dict() for item in self.evidence],
        }


class BriefingDisposition(StrEnum):
    IGNORE_FOR_BRIEFING = "ignore_for_briefing"
    LOW_PRIORITY = "low_priority"
    ARCHIVE_PROPOSAL = "archive_proposal"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class BriefingDecision:
    disposition: BriefingDisposition
    reasons: tuple[str, ...]
    mailbox_mutation_allowed: bool = False

    def __post_init__(self) -> None:
        if self.mailbox_mutation_allowed:
            raise ValueError("briefing classification cannot authorize mailbox mutation")


def briefing_decision(message: EmailMessage, decision: TriageDecision) -> BriefingDecision:
    if decision.intent is EmailIntent.BANK_SECURITY:
        return BriefingDecision(
            BriefingDisposition.ACTION_REQUIRED,
            ("bank_or_security_evidence",),
        )
    actionable = {
        ActionState.USER_DECISION,
        ActionState.REPLY,
        ActionState.FOLLOW_UP,
        ActionState.DOCUMENT_REQUIRED,
        ActionState.PICKUP,
        ActionState.VERIFY,
        ActionState.PAYMENT_REVIEW,
        ActionState.DEADLINE,
    }
    if decision.action_state in actionable:
        return BriefingDecision(
            BriefingDisposition.ACTION_REQUIRED,
            (f"action_state:{decision.action_state.value}",),
        )
    if decision.intent in {EmailIntent.NEWSLETTER, EmailIntent.NOISE}:
        return BriefingDecision(
            BriefingDisposition.IGNORE_FOR_BRIEFING,
            (f"intent:{decision.intent.value}",),
        )
    if message.junk:
        return BriefingDecision(
            BriefingDisposition.ARCHIVE_PROPOSAL,
            ("junk_signal_only_proposal",),
        )
    return BriefingDecision(BriefingDisposition.LOW_PRIORITY, ("informational",))


@dataclass(frozen=True, slots=True)
class TrustSignal:
    kind: str
    detail: str
    confidence: float


@dataclass(frozen=True, slots=True)
class EmailTrustAssessment:
    signals: tuple[TrustSignal, ...]
    requires_verification: bool
    certainty: float


_OFFICIAL_BRANDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("crédit agricole", "credit agricole"), ("credit-agricole.fr",)),
    (("paypal",), ("paypal.com", "paypal.fr")),
    (("amazon",), ("amazon.fr", "amazon.com")),
    (("ebay",), ("ebay.fr", "ebay.com")),
    (("mondial relay",), ("mondialrelay.fr",)),
)


def domain_matches_official(domain: str, official_domains: tuple[str, ...]) -> bool:
    clean = domain.strip().casefold().rstrip(".")
    for official in official_domains:
        candidate = official.strip().casefold().rstrip(".")
        if clean == candidate or clean.endswith(f".{candidate}"):
            return True
    return False


def assess_email_trust(message: EmailMessage) -> EmailTrustAssessment:
    signals: list[TrustSignal] = []
    sender_domain = _sender_domain(message.sender)
    display = _sender_display_name(message.sender).casefold()
    official_for_brand: tuple[str, ...] = ()
    for names, domains in _OFFICIAL_BRANDS:
        if not any(name in display for name in names):
            continue
        official_for_brand = domains
        if not domain_matches_official(sender_domain, domains):
            signals.append(
                TrustSignal(
                    "brand_domain_mismatch",
                    f"display brand does not align with sender domain {sender_domain or 'unknown'}",
                    0.82,
                )
            )
        break

    for raw_url in _extract_urls(message.body):
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").casefold()
        suspicious = parsed.scheme.casefold() != "https"
        if host.startswith("xn--") or _is_ip_like(host):
            suspicious = True
        if official_for_brand and host and not domain_matches_official(host, official_for_brand):
            suspicious = True
        if suspicious:
            signals.append(
                TrustSignal(
                    "suspicious_link",
                    f"untrusted link host {host or 'unknown'}",
                    0.78,
                )
            )

    lower = f"{message.subject} {message.body}".casefold()
    urgency = ("urgent", "immédiatement", "immediatement", "sous 24h")
    if any(term in lower for term in urgency):
        signals.append(TrustSignal("urgency_cue", "urgency language present", 0.62))

    certainty = min(0.92, 0.35 + sum(item.confidence for item in signals) / 6.0)
    return EmailTrustAssessment(
        signals=tuple(signals[:16]),
        requires_verification=bool(signals),
        certainty=round(certainty, 3),
    )


@dataclass(frozen=True, slots=True)
class UntrustedEmailLink:
    url: str
    provenance: ProvenanceRef
    trusted: bool = False


@dataclass(frozen=True, slots=True)
class SanitizedEmailHtml:
    text: str
    links: tuple[UntrustedEmailLink, ...]
    blocked_active_count: int
    blocked_remote_count: int


class _SafeEmailHtmlParser(HTMLParser):
    _active_tags = ("script", "style", "iframe", "object", "embed", "form")

    def __init__(self, provenance: ProvenanceRef) -> None:
        super().__init__(convert_charrefs=True)
        self.provenance = provenance
        self.text_parts: list[str] = []
        self.links: list[UntrustedEmailLink] = []
        self.blocked_active_count = 0
        self.blocked_remote_count = 0
        self._blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.casefold()
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if lower in self._active_tags:
            self.blocked_active_count += 1
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if lower in {"img", "source", "video", "audio"}:
            source = attributes.get("src", "")
            if source.startswith(("http://", "https://", "//")):
                self.blocked_remote_count += 1
        if lower == "a":
            href = attributes.get("href", "").strip()
            if href:
                self.links.append(UntrustedEmailLink(href[:2000], self.provenance))
        if lower in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.casefold()
        if lower in self._active_tags:
            if self._blocked_depth:
                self._blocked_depth -= 1
            return
        if not self._blocked_depth and lower in {"p", "div", "li", "tr"}:
            self.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth:
            self.text_parts.append(data)


def sanitize_email_html(html: str, *, provenance: ProvenanceRef) -> SanitizedEmailHtml:
    parser = _SafeEmailHtmlParser(provenance)
    try:
        parser.feed(str(html)[:200_000])
        parser.close()
    except (TypeError, ValueError):
        pass
    text = " ".join(unescape("".join(parser.text_parts)).split())[:20_000]
    return SanitizedEmailHtml(
        text=text,
        links=tuple(parser.links[:100]),
        blocked_active_count=parser.blocked_active_count,
        blocked_remote_count=parser.blocked_remote_count,
    )


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    start_at: float
    end_at: float
    window_days: int
    max_messages: int
    lane: str = "backfill"
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class EmailBackfillPolicy:
    initial_days: int = 7
    max_days: int = 90
    batch_size: int = 250

    def __post_init__(self) -> None:
        if not 1 <= self.initial_days <= 14:
            raise ValueError("initial backfill window must be between 1 and 14 days")
        if self.max_days < self.initial_days or self.max_days > 365:
            raise ValueError("invalid maximum backfill window")
        if not 1 <= self.batch_size <= 500:
            raise ValueError("backfill batch size must be between 1 and 500")

    def plan(self, now: float, *, window_days: int | None = None) -> BackfillPlan:
        end = float(now)
        if end <= 0:
            raise ValueError("backfill plan requires a positive timestamp")
        days = self.initial_days if window_days is None else int(window_days)
        days = max(1, min(days, self.max_days))
        return BackfillPlan(
            start_at=end - (days * 86_400),
            end_at=end,
            window_days=days,
            max_messages=self.batch_size,
        )

    def next_window_days(self, current_days: int) -> int:
        return min(self.max_days, max(self.initial_days, int(current_days) * 2))


def save_email_backfill_checkpoint(
    store: SituationStore,
    cursor: str,
    *,
    source_version: str = "",
    evidence_hash: str = "",
) -> None:
    store.checkpoint(
        "email",
        cursor,
        lane="backfill",
        source_version=source_version,
        evidence_hash=evidence_hash,
    )


@dataclass(frozen=True, slots=True)
class EmailWorkItem:
    message: EmailMessage
    decision: TriageDecision
    lane: str = "live"
    sequence: int = 0

    def __post_init__(self) -> None:
        lane = self.lane.strip().casefold()
        if lane not in {"live", "backfill"}:
            raise ValueError("email work lane must be live or backfill")
        object.__setattr__(self, "lane", lane)
        object.__setattr__(self, "sequence", max(0, int(self.sequence)))


def prioritize_email_work(items: list[EmailWorkItem]) -> list[EmailWorkItem]:
    return sorted(items, key=_email_work_key)


def _email_work_key(item: EmailWorkItem) -> tuple[int, int, int, float, str]:
    evidence_backed = item.decision.confidence >= 0.7
    importance = 3
    if evidence_backed and item.decision.intent is EmailIntent.BANK_SECURITY:
        importance = 0
    elif evidence_backed and item.decision.action_state in {
        ActionState.DEADLINE,
        ActionState.PAYMENT_REVIEW,
        ActionState.VERIFY,
        ActionState.REPLY,
        ActionState.DOCUMENT_REQUIRED,
        ActionState.PICKUP,
    }:
        importance = 1
    elif item.decision.intent in {EmailIntent.NEWSLETTER, EmailIntent.NOISE}:
        importance = 5
    lane_rank = 0 if item.lane == "live" else 1
    return (
        importance,
        lane_rank,
        item.sequence,
        -item.message.received_at,
        item.message.message_id,
    )


@dataclass(frozen=True, slots=True)
class ThreadCompactSummary:
    thread_key: str
    message_count: int
    latest_state: str
    open_question: str
    responsibility: str
    action_state: str
    commitment: str
    deadline: str | None
    requested_document: str
    entities: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]
    recent_messages: tuple[dict[str, object], ...]


def compact_email_thread(
    state: EmailThreadState,
    messages: list[EmailMessage],
    meanings: list[StructuredEmailMeaning],
    *,
    max_messages: int = 5,
) -> ThreadCompactSummary:
    if len(messages) != len(meanings):
        raise ValueError("messages and meanings must be aligned")
    cap = max(1, min(int(max_messages), 20))
    entities: list[str] = []
    provenance: list[ProvenanceRef] = []
    for meaning in meanings:
        for entity in meaning.entities:
            if entity not in entities:
                entities.append(entity)
        for evidence in meaning.provenance:
            if not _contains_provenance(provenance, evidence):
                provenance.append(evidence)
    for evidence in state.evidence:
        if not _contains_provenance(provenance, evidence):
            provenance.append(evidence)

    recent = tuple(
        {
            "message_id": item.message_id,
            "sender": item.sender[:300],
            "subject": item.subject[:300],
            "received_at": item.received_at,
        }
        for item in messages[-cap:]
    )
    return ThreadCompactSummary(
        thread_key=state.thread_key,
        message_count=len(messages),
        latest_state=state.latest_state,
        open_question=state.open_question,
        responsibility=state.responsibility.value,
        action_state=state.action_state.value,
        commitment=state.commitment,
        deadline=state.deadline,
        requested_document=state.requested_document,
        entities=tuple(entities[:100]),
        provenance=tuple(provenance[-200:]),
        recent_messages=recent,
    )


def _contains_provenance(items: list[ProvenanceRef], candidate: ProvenanceRef) -> bool:
    return any(
        item.source == candidate.source and item.source_id == candidate.source_id for item in items
    )


def _future_father_promise(message: EmailMessage) -> tuple[str, str, str | None] | None:
    if not message.sender_is_father:
        return None
    text = " ".join(message.body.split())
    patterns = (
        r"\bje\s+vous\s+l['’]enverrai\s+[^.!?]{2,80}",
        r"\bje\s+vous\s+(?:enverrai|transmettrai)\s+[^.!?]{2,160}",
        r"\bje\s+vais\s+vous\s+(?:envoyer|transmettre)\s+[^.!?]{2,160}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        wording = _deadline_source_wording(text, None)
        due = _normalize_deadline(wording, message.received_at)
        obligation = "Envoyer le document promis"
        if "transmet" in match.group(0).casefold():
            obligation = "Transmettre le document promis"
        return obligation, wording, due
    return None


def _looks_future_promise(text: str) -> bool:
    lower = text.casefold().replace("’", "'")
    markers = (
        "je vous l'enverrai",
        "je vous enverrai",
        "je vous transmettrai",
        "je vais vous envoyer",
        "je vais vous transmettre",
    )
    return any(marker in lower for marker in markers)


def _deadline_source_wording(text: str, detector_deadline: str | None) -> str:
    compact = " ".join(text.split())
    patterns = (
        r"\b(avant\s+(?:le\s+)?(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche))\b",
        r"\b(d['’]ici\s+(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain))\b",
        r"\b(demain)\b",
        r"\b(avant\s+le\s+[0-3]?\d[/-][01]?\d(?:[/-]\d{2,4})?)\b",
        r"\b(au\s+plus\s+tard\s+le\s+[0-3]?\d[/-][01]?\d(?:[/-]\d{2,4})?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return " ".join(str(detector_deadline or "").split())[:200]


def _normalize_deadline(raw: str | None, observed_at: float) -> str | None:
    value = " ".join(str(raw or "").casefold().replace("’", "'").split()).strip()
    if not value:
        return None
    local = datetime.fromtimestamp(float(observed_at), tz=_PARIS)
    if "demain" in value:
        return (local.date() + timedelta(days=1)).isoformat()
    for name, weekday in _WEEKDAYS.items():
        if name not in value:
            continue
        delta = (weekday - local.weekday()) % 7
        if delta == 0:
            delta = 7
        return (local.date() + timedelta(days=delta)).isoformat()
    numeric = re.search(r"([0-3]?\d)[/-]([01]?\d)(?:[/-](\d{2,4}))?", value)
    if numeric:
        day = int(numeric.group(1))
        month = int(numeric.group(2))
        raw_year = numeric.group(3)
        year = local.year if raw_year is None else int(raw_year)
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day, tzinfo=_PARIS).date().isoformat()
        except ValueError:
            return None
    return None


def _sender_domain(sender: str) -> str:
    match = re.search(r"<([^<>\s]+@[^<>\s]+)>", sender)
    address = match.group(1) if match else sender.strip()
    if "@" not in address:
        return ""
    return address.rsplit("@", 1)[1].strip().casefold().rstrip(">.")


def _sender_display_name(sender: str) -> str:
    return sender.split("<", 1)[0].strip().strip('"')


def _extract_urls(text: str) -> tuple[str, ...]:
    return tuple(
        match.rstrip(".,);]>'\"")[:2000]
        for match in re.findall(r"https?://[^\s<>\"']+", text, flags=re.IGNORECASE)
    )[:100]


def _is_ip_like(host: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host))
