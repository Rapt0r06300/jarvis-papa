import re
from dataclasses import dataclass

from jarvis_papa.actions import ActionKind, ActionOption, action_queue
from jarvis_papa.speech import SpeechImportance


@dataclass(frozen=True, slots=True)
class IncomingMail:
    message_id: int | None
    header_message_id: str | None
    author: str
    subject: str
    body: str
    folder: str = "Inbox"
    list_unsubscribe: bool = False
    junk: bool = False
    date: str | None = None


@dataclass(frozen=True, slots=True)
class MailAssessment:
    importance: SpeechImportance
    action_required: bool
    is_noise: bool
    category: str
    summary: str
    spoken_summary: str
    search_terms: tuple[str, ...]
    priority_score: int
    confidence: float
    deadline_text: str | None
    reason: str
    recommended_action: str
    sensitive: bool


class MailAssistant:
    """Conservative mail triage designed for a low-friction personal secretary."""

    _newsletter_terms = (
        "newsletter",
        "désabonner",
        "unsubscribe",
        "promotion",
        "soldes",
        "offre commerciale",
        "nos offres",
        "voir dans le navigateur",
        "code promo",
    )
    _action_terms = (
        "merci de",
        "veuillez",
        "merci d'envoyer",
        "merci de transmettre",
        "transmettre",
        "joindre",
        "confirmer",
        "répondre",
        "avant le",
        "au plus tard",
        "document demandé",
        "nous retourner",
        "à compléter",
        "a completer",
    )
    _urgent_terms = (
        "urgent",
        "urgence",
        "au plus tard",
        "dernier rappel",
        "mise en demeure",
        "sous 24 heures",
        "sous 48 heures",
    )
    _important_terms = (
        "facture",
        "assurance",
        "banque",
        "impôt",
        "impots",
        "rendez-vous",
        "échéance",
        "relance",
        "contrat",
        "administration",
        "remboursement",
        "mutuelle",
        "retraite",
        "santé",
        "sante",
        "dossier",
    )
    _suspicious_terms = (
        "mot de passe",
        "code de sécurité",
        "code de securite",
        "carte bancaire",
        "coordonnées bancaires",
        "coordonnees bancaires",
        "virement immédiat",
        "virement immediat",
        "cliquez immédiatement",
        "cliquez immediatement",
        "compte suspendu",
        "compte bloqué",
        "compte bloque",
    )
    _file_terms = (
        "facture",
        "devis",
        "attestation",
        "justificatif",
        "document",
        "pdf",
        "photo",
        "contrat",
        "relevé",
        "releve",
        "rapport",
        "ordonnance",
    )
    _sensitive_terms = _important_terms + _suspicious_terms + (
        "numéro de dossier",
        "numero de dossier",
        "iban",
        "salaire",
    )

    def assess(self, mail: IncomingMail) -> MailAssessment:
        clean_body = self._clean_body(mail.body)
        combined = f"{mail.subject}\n{clean_body}".casefold()
        action_required = any(term in combined for term in self._action_terms)
        has_important_term = any(term in combined for term in self._important_terms)
        urgent = any(term in combined for term in self._urgent_terms)
        suspicious = any(term in combined for term in self._suspicious_terms)
        marketing = mail.list_unsubscribe or any(term in combined for term in self._newsletter_terms)
        deadline = self._extract_deadline(clean_body)
        sensitive = any(term in combined for term in self._sensitive_terms)

        score = 0
        if action_required:
            score += 35
        if has_important_term:
            score += 25
        if urgent:
            score += 30
        if deadline:
            score += 15
        if suspicious:
            score += 25
        score = min(100, score)

        # Newsletter detection is deliberately conservative: a bulk signal never wins over
        # an explicit administrative/action signal. It is safer to show one extra mail than
        # to silently hide something important.
        newsletter = (mail.junk or marketing) and not action_required and not has_important_term
        if suspicious:
            category = "suspicious"
            importance = SpeechImportance.CRITICAL if urgent else SpeechImportance.HIGH
            score = max(score, 80)
        elif newsletter:
            category = "newsletter"
            importance = SpeechImportance.LOW
            score = min(score, 15)
        elif urgent and action_required:
            category = "important"
            importance = SpeechImportance.CRITICAL
            score = max(score, 90)
        elif action_required or has_important_term:
            category = "important"
            importance = SpeechImportance.HIGH
            score = max(score, 60)
        else:
            category = "normal"
            importance = SpeechImportance.NORMAL
            score = max(score, 20)

        summary = self._summary(clean_body, mail.subject, deadline)
        spoken_summary = self._spoken_summary(clean_body, mail.subject, deadline)
        reason = self._reason(category, action_required, deadline, urgent)
        recommended = self._recommended_action(category, action_required, combined)
        confidence = self._confidence(
            category=category,
            marketing=marketing,
            action_required=action_required,
            important=has_important_term,
            suspicious=suspicious,
        )
        return MailAssessment(
            importance=importance,
            action_required=action_required,
            is_noise=category == "newsletter",
            category=category,
            summary=summary,
            spoken_summary=spoken_summary,
            search_terms=self._extract_search_terms(mail.subject, clean_body),
            priority_score=score,
            confidence=confidence,
            deadline_text=deadline,
            reason=reason,
            recommended_action=recommended,
            sensitive=sensitive,
        )

    def create_action_card(self, mail: IncomingMail, assessment: MailAssessment):
        dedupe_key = mail.header_message_id or (
            f"tb:{mail.message_id}" if mail.message_id is not None else None
        )
        common_metadata = {
            "category": assessment.category,
            "message_id": mail.message_id,
            "header_message_id": mail.header_message_id,
            "folder": mail.folder,
            "deadline_text": assessment.deadline_text,
            "priority_score": assessment.priority_score,
            "confidence": assessment.confidence,
            "recommended_action": assessment.recommended_action,
            "reason": assessment.reason,
            "sensitive": assessment.sensitive,
            "dedupe_key": dedupe_key,
        }

        if assessment.category == "newsletter":
            return action_queue.create(
                title=mail.subject or "Newsletter",
                summary=assessment.summary,
                source=mail.author or "Newsletter",
                importance=SpeechImportance.LOW.value,
                speech_text=None,
                options=[],
                metadata=common_metadata,
                dedupe_key=dedupe_key,
                priority_score=assessment.priority_score,
            )

        # Ordinary informational mail does not deserve a permanent card. Robert can still
        # read it in Thunderbird; Jarvis only surfaces what is likely to matter.
        if assessment.category == "normal":
            return None

        options = [
            ActionOption(
                id="open-email",
                label="Voir le mail",
                kind=ActionKind.OPEN_EMAIL,
                payload={
                    "message_id": mail.message_id,
                    "header_message_id": mail.header_message_id,
                },
            ),
        ]
        if assessment.search_terms:
            options.insert(
                0,
                ActionOption(
                    id="find-files",
                    label="Chercher le document",
                    kind=ActionKind.SEARCH_FILES,
                    payload={"query": " ".join(assessment.search_terms[:4])},
                ),
            )
        if assessment.action_required:
            options.append(
                ActionOption(
                    id="prepare-reply",
                    label="Préparer une réponse",
                    kind=ActionKind.SEND_REPLY,
                    payload={
                        "message_id": mail.message_id,
                        "header_message_id": mail.header_message_id,
                        "subject": mail.subject,
                        "author": mail.author,
                        "draft_only": True,
                    },
                    requires_confirmation=True,
                ),
            )

        sender = self._spoken_sender(mail.author)
        prefix = "message à vérifier" if assessment.category == "suspicious" else "mail important"
        speech_text = f"Robert, {prefix} de {sender}. {assessment.spoken_summary}"
        return action_queue.create(
            title=mail.subject or "Nouveau message important",
            summary=assessment.summary,
            source=mail.author or "E-mail",
            importance=assessment.importance.value,
            speech_text=speech_text,
            options=options,
            metadata={
                **common_metadata,
                "search_terms": list(assessment.search_terms),
                "action_required": assessment.action_required,
                "author": mail.author,
                "subject": mail.subject,
                "body": mail.body[:8000],
            },
            dedupe_key=dedupe_key,
            priority_score=assessment.priority_score,
        )

    @staticmethod
    def _clean_body(body: str) -> str:
        text = body.replace("\u00a0", " ")
        # Avoid re-summarising long quoted conversations and common signature noise.
        text = re.split(r"(?:^|\n)(?:Le .+ a écrit\s*:|On .+ wrote\s*:)", text, maxsplit=1)[0]
        text = re.split(r"\n--\s*\n", text, maxsplit=1)[0]
        return re.sub(r"\s+", " ", text).strip()

    def _summary(self, text: str, subject: str, deadline: str | None) -> str:
        if not text:
            return f"Objet : {subject}" if subject else "Nouveau message reçu."
        sentence = self._best_sentence(text)
        if deadline and deadline.casefold() not in sentence.casefold():
            sentence = f"{sentence} Échéance : {deadline}."
        return self._limit(sentence, 230)

    def _spoken_summary(self, text: str, subject: str, deadline: str | None) -> str:
        if not text:
            return f"Objet : {subject}." if subject else "Le message ne contient pas de texte."
        sentence = self._best_sentence(text)
        if deadline and deadline.casefold() not in sentence.casefold():
            sentence = f"{sentence} Échéance {deadline}."
        return self._limit(sentence, 175)

    def _best_sentence(self, text: str) -> str:
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
        if not sentences:
            return text
        terms = self._action_terms + self._urgent_terms + self._important_terms

        def score(sentence: str) -> tuple[int, int]:
            lowered = sentence.casefold()
            return (sum(1 for term in terms if term in lowered), -len(sentence))

        best = max(sentences[:12], key=score)
        best = re.sub(r"^(bonjour|bonsoir)(\s+[^,.]{0,60})?[,!]?\s*", "", best, flags=re.I)
        return best[:400].strip() or sentences[0]

    @staticmethod
    def _extract_deadline(text: str) -> str | None:
        patterns = (
            r"(?:avant|au plus tard|d'ici|pour)\s+(?:le\s+)?([0-3]?\d[/-][01]?\d(?:[/-]\d{2,4})?)",
            r"(?:avant|au plus tard|d'ici|pour)\s+(?:le\s+)?([0-3]?\d\s+(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)(?:\s+\d{4})?)",
            r"(?:avant|au plus tard|d'ici|pour)\s+(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return match.group(1).strip()
        return None

    def _extract_search_terms(self, subject: str, body: str) -> tuple[str, ...]:
        combined = f"{subject} {body}".casefold()
        found = [term for term in self._file_terms if term in combined]
        # Identifiers, amounts and distinctive long words make local file search much more useful.
        candidates = re.findall(r"\b(?:[A-Z0-9][A-Z0-9._/-]{3,}|\d+[.,]?\d*\s?€)\b", f"{subject} {body}")
        for item in candidates:
            normalized = item.strip().casefold()
            if normalized and normalized not in found:
                found.append(normalized)
            if len(found) >= 6:
                break
        return tuple(found[:6])

    @staticmethod
    def _reason(category: str, action_required: bool, deadline: str | None, urgent: bool) -> str:
        if category == "newsletter":
            return "Message commercial sans action importante détectée."
        if category == "suspicious":
            return "Le message contient une demande sensible qui mérite une vérification humaine."
        if urgent or deadline:
            return "Une action ou une échéance importante a été détectée."
        if action_required:
            return "Le correspondant demande explicitement une action ou une réponse."
        return "Le sujet contient des éléments administratifs ou personnels importants."

    def _recommended_action(self, category: str, action_required: bool, combined: str) -> str:
        if category == "suspicious":
            return "Ouvrir le mail et vérifier l'expéditeur avant toute action."
        if category == "newsletter":
            return "Ranger dans Newsletters."
        if action_required and any(term in combined for term in self._file_terms):
            return "Chercher le document demandé puis préparer la réponse."
        if action_required:
            return "Lire la demande puis préparer une réponse."
        return "Lire le mail quand Robert est disponible."

    @staticmethod
    def _confidence(
        *,
        category: str,
        marketing: bool,
        action_required: bool,
        important: bool,
        suspicious: bool,
    ) -> float:
        if suspicious:
            return 0.93
        if category == "newsletter" and marketing:
            return 0.9
        if action_required and important:
            return 0.94
        if action_required or important:
            return 0.84
        return 0.65

    @staticmethod
    def _limit(text: str, limit: int) -> str:
        cleaned = " ".join(text.split()).strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip(" ,;:-") + "..."

    @staticmethod
    def _spoken_sender(author: str) -> str:
        cleaned = re.sub(r"<[^>]+>", "", author).strip().strip('"')
        return cleaned or "un correspondant"


mail_assistant = MailAssistant()
