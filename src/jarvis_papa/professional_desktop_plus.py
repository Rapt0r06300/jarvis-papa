from __future__ import annotations

import sys
from functools import partial

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from jarvis_papa.config import settings
from jarvis_papa.professional_desktop import BackendService, ProfessionalMainWindow


class JarvisProfessionalWindow(ProfessionalMainWindow):
    """Extend the canonical desktop without duplicating its visual architecture."""

    def __init__(self) -> None:
        super().__init__()
        self._install_assistance_menu()

    def _install_assistance_menu(self) -> None:
        menu = self.menuBar().addMenu("Aide")

        repair = QAction("Vérifier et réparer Jarvis", self)
        repair.triggered.connect(self.repair_jarvis)
        menu.addAction(repair)

        voice = QAction("Vérifier la voix de Jarvis", self)
        voice.triggered.connect(self.check_voice_quality)
        menu.addAction(voice)

    def handle_option(self, card: dict[str, object], option: dict[str, object]) -> None:
        if str(option.get("id") or "") == "send-prepared":
            payload = option.get("payload") if isinstance(option.get("payload"), dict) else {}
            draft_command_id = str(payload.get("draft_command_id") or "")
            self._begin_verified_send(card, draft_command_id)
            return
        super().handle_option(card, option)

    def _begin_verified_send(self, card: dict[str, object], draft_command_id: str) -> None:
        card_id = str(card.get("id") or "")
        if not card_id or not draft_command_id:
            self._task_failed("Je ne retrouve pas le brouillon préparé. Prépare-le à nouveau.")
            return
        self.begin_activity(
            "Je vérifie le brouillon exact avant de te demander l'autorisation d'envoi.",
            wait_text=(
                "Je contrôle le destinataire, l'objet, les pièces jointes et le contenu du brouillon. "
                "Cela peut prendre quelques instants."
            ),
        )
        self._worker(
            lambda: self.api.request(
                "POST",
                f"/api/advanced/mail/{card_id}/send/inspect",
                payload={"draft_command_id": draft_command_id},
                timeout=10,
            ),
            partial(self._send_inspection_started, card),
        )

    def _send_inspection_started(
        self,
        card: dict[str, object],
        result: dict[str, object],
    ) -> None:
        if not bool(result.get("ok")) or not result.get("command_id"):
            self._task_failed(str(result.get("detail") or "Je n'ai pas pu vérifier le brouillon."))
            return
        command_id = str(result["command_id"])
        self.activity_title.setText("Je vérifie le brouillon dans Thunderbird")
        self.activity_detail.setText(
            str(result.get("detail") or "J'attends l'instantané vérifié du brouillon.")
        )
        self._poll_send_inspection(card, command_id, 0)

    def _poll_send_inspection(
        self,
        card: dict[str, object],
        command_id: str,
        attempt: int,
    ) -> None:
        if attempt >= 30:
            self.finish_partial(
                "Thunderbird ne m'a pas encore confirmé le contenu du brouillon. Je n'envoie rien."
            )
            return
        self._worker(
            lambda: self.api.request(
                "GET", f"/api/thunderbird/commands/{command_id}", timeout=3
            ),
            partial(self._send_inspection_result, card, command_id, attempt),
            on_error=lambda _message: QTimer.singleShot(
                500,
                partial(self._poll_send_inspection, card, command_id, attempt + 1),
            ),
        )

    def _send_inspection_result(
        self,
        card: dict[str, object],
        command_id: str,
        attempt: int,
        result: dict[str, object],
    ) -> None:
        status = str(result.get("status") or "pending")
        if status == "failed":
            self.finish_activity(
                str(result.get("error") or "Thunderbird n'a pas pu vérifier ce brouillon."),
                success=False,
            )
            return
        if status != "succeeded":
            QTimer.singleShot(
                500,
                partial(self._poll_send_inspection, card, command_id, attempt + 1),
            )
            return
        card_id = str(card.get("id") or "")
        self._worker(
            lambda: self.api.request(
                "GET",
                f"/api/advanced/mail/{card_id}/send/plan/{command_id}",
                timeout=4,
            ),
            partial(self._send_plan_ready, card, command_id),
        )

    def _send_plan_ready(
        self,
        card: dict[str, object],
        inspect_command_id: str,
        plan: dict[str, object],
    ) -> None:
        if not bool(plan.get("ok")):
            self._task_failed(str(plan.get("detail") or "Le brouillon n'est pas vérifiable."))
            return
        action_key = str(plan.get("action_key") or "mail.send_reply")
        description = str(plan.get("description") or "Envoyer ce brouillon.")
        binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
        self.announce(description)
        token = self.authorize(action_key, description, binding)
        if not token:
            self.finish_activity("D'accord. Le mail reste en brouillon et rien n'est envoyé.", speak=False)
            return
        card_id = str(card.get("id") or "")
        self.begin_activity(
            "J'envoie maintenant le brouillon exactement vérifié.",
            wait_text=(
                "Thunderbird est en train d'envoyer le message. J'attends sa preuve de réussite avant de te dire que c'est fait."
            ),
        )
        self._worker(
            lambda: self.api.request(
                "POST",
                f"/api/advanced/mail/{card_id}/send",
                payload={
                    "inspect_command_id": inspect_command_id,
                    "authorization_token": token,
                },
                timeout=10,
            ),
            self._send_requested,
        )

    def _send_requested(self, result: dict[str, object]) -> None:
        if not bool(result.get("ok")) or not result.get("command_id"):
            self._task_failed(str(result.get("detail") or "L'envoi a été bloqué."))
            return
        self.activity_detail.setText(
            "La demande est partie vers Thunderbird. Je vérifie maintenant l'envoi réel."
        )
        self._poll_send_confirmation(str(result["command_id"]), 0)

    def _poll_send_confirmation(self, command_id: str, attempt: int) -> None:
        if attempt >= 40:
            self.finish_partial(
                "Je n'ai pas reçu de preuve d'envoi de Thunderbird. Je ne considère pas le mail comme envoyé."
            )
            return
        self._worker(
            lambda: self.api.request(
                "GET", f"/api/thunderbird/commands/{command_id}", timeout=3
            ),
            partial(self._send_confirmation_result, command_id, attempt),
            on_error=lambda _message: QTimer.singleShot(
                500,
                partial(self._poll_send_confirmation, command_id, attempt + 1),
            ),
        )

    def _send_confirmation_result(
        self,
        command_id: str,
        attempt: int,
        result: dict[str, object],
    ) -> None:
        status = str(result.get("status") or "pending")
        if status == "failed":
            self.finish_activity(
                str(result.get("error") or "Thunderbird n'a pas confirmé l'envoi."),
                success=False,
            )
            return
        if status != "succeeded":
            QTimer.singleShot(
                500,
                partial(self._poll_send_confirmation, command_id, attempt + 1),
            )
            return
        proof = result.get("result") if isinstance(result.get("result"), dict) else {}
        if proof.get("verified") is not True or str(proof.get("mode") or "") != "sendNow":
            self.finish_partial(
                "Thunderbird a répondu, mais la preuve ne suffit pas pour confirmer un envoi immédiat."
            )
            return
        self.finish_activity("Thunderbird m'a confirmé que le mail a bien été envoyé.")
        self.refresh()

    def _thunderbird_command_result(
        self,
        command_id: str,
        attempt: int,
        result: dict[str, object],
    ) -> None:
        super()._thunderbird_command_result(command_id, attempt, result)
        if str(result.get("status") or "") == "succeeded":
            QTimer.singleShot(250, self.refresh)

    def send_chat(self) -> None:
        self._worker(
            lambda: self.api.request("POST", "/api/advanced/voice/stop", payload={}, timeout=2),
            lambda _result: None,
            on_error=lambda _message: None,
        )
        super().send_chat()

    def cancel_chat(self) -> None:
        self._worker(
            lambda: self.api.request("POST", "/api/advanced/voice/stop", payload={}, timeout=2),
            lambda _result: None,
            on_error=lambda _message: None,
        )
        super().cancel_chat()

    def _voice_events(self, payload: dict[str, object]) -> None:
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        for event in events:
            if not isinstance(event, dict):
                continue
            self.last_voice_event = max(self.last_voice_event, int(event.get("id") or 0))
            event_type = str(event.get("type") or "")
            text = str(event.get("text") or "Je te parle.")
            if event_type == "speech_started":
                self.speaking_timer.stop()
                self.caption.setText(text)
                self.avatar.set_speaking(True)
            elif event_type in {"speech_finished", "speech_interrupted", "speech_failed"}:
                self.speaking_timer.stop()
                self._stop_speaking()
            elif not event_type:
                duration = max(1.6, float(event.get("duration_estimate_seconds") or 2.0))
                self.caption.setText(text)
                self.avatar.set_speaking(True)
                self.speaking_timer.start(int((duration + 0.5) * 1000))

    def repair_jarvis(self) -> None:
        self.begin_activity(
            "Je vérifie ce que je peux réparer sans risque.",
            wait_text="Je contrôle les composants essentiels avant de te proposer une réparation.",
        )
        self._worker(
            lambda: self.api.request("GET", "/api/advanced/repair/plan", timeout=12),
            self._repair_plan_ready,
        )

    def _repair_plan_ready(self, plan: dict[str, object]) -> None:
        items = plan.get("components") if isinstance(plan.get("components"), list) else []
        components = sorted(
            {
                str(item.get("component") or "").strip().casefold()
                for item in items
                if isinstance(item, dict) and item.get("component")
            }
        )
        if not components:
            self.finish_activity("Tout ce que je peux réparer automatiquement est déjà en ordre.")
            return
        labels = [
            str(item.get("label") or item.get("component") or "composant")
            for item in items
            if isinstance(item, dict)
        ]
        human = ", ".join(labels[:5])
        description = f"Jarvis va tenter de réparer : {human}."
        token = self.authorize("jarvis.repair", description, {"components": components})
        if not token:
            self.finish_activity("D'accord. Je ne change rien.", speak=False)
            return
        self.begin_activity(
            "Je répare les composants autorisés, avec un nombre d'essais limité.",
            wait_text="Je continue la réparation. Si un composant résiste, j'arrêterai plutôt que de boucler.",
        )
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/advanced/repair",
                payload={"components": components, "authorization_token": token},
                timeout=30,
            ),
            self._repair_result,
        )

    def _repair_result(self, result: dict[str, object]) -> None:
        state = str(result.get("state") or "unknown")
        detail = str(result.get("detail") or "Réparation terminée.")
        if state == "success":
            self.finish_activity(detail)
        elif state == "partial":
            self.finish_partial(detail)
        else:
            self.finish_activity(detail, success=False)
        QTimer.singleShot(400, self.refresh_diagnostics)

    def check_voice_quality(self) -> None:
        self.begin_activity("Je vérifie la meilleure voix disponible.")
        self._worker(
            lambda: self.api.request("GET", "/api/advanced/voice/quality", timeout=8),
            self._voice_quality_result,
        )

    def _voice_quality_result(self, result: dict[str, object]) -> None:
        detail = str(result.get("detail") or "Je n'ai pas pu vérifier la voix.")
        if bool(result.get("premium_ready")):
            self.finish_activity(detail)
        elif bool(result.get("ok")):
            self.finish_partial(detail)
        else:
            self.finish_activity(detail, success=False)


def run() -> None:
    """Start the enhanced canonical Windows desktop and hidden localhost bridge."""

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setOrganizationName("Jarvis Papa")
    app.setFont(QFont("Segoe UI", 10))

    lock = QLockFile(str((settings.runtime_dir / "jarvis-desktop.lock").resolve()))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Jarvis", "Jarvis est déjà ouvert sur cet ordinateur.")
        return

    backend = BackendService()
    if not backend.start():
        QMessageBox.critical(
            None,
            "Jarvis",
            "Jarvis n'a pas pu démarrer son service local. Redémarre l'application ou lance le diagnostic.",
        )
        lock.unlock()
        return

    window = JarvisProfessionalWindow()
    window.show()
    exit_code = app.exec()
    backend.stop()
    lock.unlock()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    run()
