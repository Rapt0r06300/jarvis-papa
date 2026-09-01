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


@dataclass(frozen=True, slots=True)
class MailAssessment:
    importance: SpeechImportance
    action_required: bool
    is_noise: bool
    category: str
    summary: str
    spoken_summary: str
    search_terms: tuple[str, ...]


class MailAssistant:
    _noise_terms = (
        "newsletter",
        "désabonner",
        "unsubscribe",
        "promotion",
        "soldes",
        "offre commerciale",
        "nos offres",
        "voir dans le navigateur",
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
    )
    _important_terms = (
        "urgent",
        "important",
        "facture",
        "assurance",
        "banque",
        "impôt",
        "rendez-vous",
        "échéance",
        "relance",
        "contrat",
        "administration",
        "remboursement",
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
        "rapport",
    )

    def assess(self, mail: IncomingMail) -> MailAssessment:
        combined = f"{mail.subject}\n{mail.body}".lower()
        is_noise = any(term in combined for term in self._noise_terms)
        action_required = any(term in combined for term in self._action_terms)
        has_important_term = any(term in combined for term in self._important_terms)

        if is_noise and not action_required and not has_important_term:
            importance = SpeechImportance.LOW
            category = "newsletter"
        elif "urgent" in combined or "au plus tard" in combined:
            importance = SpeechImportance.CRITICAL if action_required else SpeechImportance.HIGH
            category = "important"
        elif action_required or has_important_term:
            importance = SpeechImportance.HIGH
            category = "important"
        else:
            importance = SpeechImportance.NORMAL
            category = "normal"

        summary = self._summarize(mail)
        return MailAssessment(
            importance=importance,
            action_required=action_required,
            is_noise=category == "newsletter",
            category=category,
            summary=summary,
            spoken_summary=self._spoken_summary(mail),
            search_terms=self._extract_search_terms(combined),
        )

    def create_action_card(self, mail: IncomingMail, assessment: MailAssessment):
        if assessment.category == "newsletter":
            return action_queue.create(
                title=mail.subject or "Newsletter",
                summary=assessment.summary,
                source=mail.author or "Newsletter",
                importance=SpeechImportance.LOW.value,
                speech_text=None,
                options=[],
                metadata={
                    "category": "newsletter",
                    "message_id": mail.message_id,
                    "header_message_id": mail.header_message_id,
                    "folder": mail.folder,
                },
            )

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
                    label="Chercher les documents",
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

        speech_text = None
        if assessment.category == "important":
            sender = self._spoken_sender(mail.author)
            speech_text = f"Robert, mail important de {sender}. {assessment.spoken_summary}"

        return action_queue.create(
            title=mail.subject or "Nouveau message",
            summary=assessment.summary,
            source=mail.author or "E-mail",
            importance=assessment.importance.value,
            speech_text=speech_text,
            options=options,
            metadata={
                "category": assessment.category,
                "message_id": mail.message_id,
                "header_message_id": mail.header_message_id,
                "folder": mail.folder,
                "search_terms": list(assessment.search_terms),
                "action_required": assessment.action_required,
                "author": mail.author,
                "subject": mail.subject,
                "body": mail.body[:8000],
            },
        )

    @staticmethod
    def _clean_body(body: str) -> str:
        return re.sub(r"\s+", " ", body).strip()

    def _summarize(self, mail: IncomingMail) -> str:
        text = self._clean_body(mail.body)
        if not text:
            return f"Objet : {mail.subject}" if mail.subject else "Nouveau message reçu."
        if len(text) <= 220:
            return text
        return text[:217].rstrip() + "..."

    def _spoken_summary(self, mail: IncomingMail) -> str:
        text = self._clean_body(mail.body)
        if not text:
            return f"Objet : {mail.subject}." if mail.subject else "Le message ne contient pas de texte."
        first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
        summary = first_sentence or text
        if len(summary) > 150:
            summary = summary[:147].rstrip() + "..."
        return summary

    def _extract_search_terms(self, text: str) -> tuple[str, ...]:
        found = [term for term in self._file_terms if term in text]
        words = re.findall(r"[a-zà-ÿ0-9][a-zà-ÿ0-9._-]{2,}", text, flags=re.IGNORECASE)
        for word in words:
            normalized = word.lower()
            if normalized in {"merci", "bonjour", "cordialement", "document", "veuillez"}:
                continue
            if (
                normalized not in found
                and len(found) < 6
                and (any(char.isdigit() for char in normalized) or len(normalized) >= 6)
            ):
                found.append(normalized)
        return tuple(found[:6])

    @staticmethod
    def _spoken_sender(author: str) -> str:
        cleaned = re.sub(r"<[^>]+>", "", author).strip()
        return cleaned or "un correspondant"


mail_assistant = MailAssistant()
