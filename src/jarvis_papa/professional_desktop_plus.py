from __future__ import annotations

import sys
from functools import partial

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from jarvis_papa.config import settings
from jarvis_papa.memory_center_dialog import MemoryCenterDialog
from jarvis_papa.overlay import GlobalOverlayHotkey, JarvisOverlay
from jarvis_papa.professional_desktop import BackendService, ProfessionalMainWindow
from jarvis_papa.system_reliability import backup_manager, session_recovery


class JarvisProfessionalWindow(ProfessionalMainWindow):
    """Extend the canonical desktop without duplicating its visual architecture."""

    def __init__(self) -> None:
        super().__init__()
        self._memory_dialog: MemoryCenterDialog | None = None
        self._tray_icon: QSystemTrayIcon | None = None
        self._proactive_poll_busy = False
        self.last_proactive_event = 0
        self._install_assistance_menu()
        self._install_overlay()
        self._install_notifications()

    def _install_assistance_menu(self) -> None:
        menu = self.menuBar().addMenu("Aide")

        memory = QAction("Ce que Jarvis retient", self)
        memory.triggered.connect(self.open_memory_center)
        menu.addAction(memory)

        overlay = QAction("Afficher Jarvis rapidement (Ctrl+Alt+J)", self)
        overlay.triggered.connect(self.toggle_overlay)
        menu.addAction(overlay)

        menu.addSeparator()

        repair = QAction("Vérifier et réparer Jarvis", self)
        repair.triggered.connect(self.repair_jarvis)
        menu.addAction(repair)

        voice = QAction("Vérifier la voix de Jarvis", self)
        voice.triggered.connect(self.check_voice_quality)
        menu.addAction(voice)

        backup = QAction("Créer une sauvegarde maintenant", self)
        backup.triggered.connect(self.create_backup)
        menu.addAction(backup)

        startup = QAction("Configurer le démarrage avec Windows", self)
        startup.triggered.connect(self.configure_startup)
        menu.addAction(startup)

        menu.addSeparator()

        stop = QAction("Arrêter Jarvis immédiatement", self)
        stop.triggered.connect(self.emergency_stop)
        menu.addAction(stop)

        resume = QAction("Réactiver Jarvis après un arrêt", self)
        resume.triggered.connect(self.clear_emergency_stop)
        menu.addAction(resume)

    def _install_overlay(self) -> None:
        self.overlay = JarvisOverlay(
            self,
            on_query=self._overlay_query,
            on_mail=lambda: self._overlay_query("Quels sont mes mails importants ?"),
            on_documents=lambda: self._overlay_query("Retrouve mes documents importants."),
            on_stop=self.emergency_stop,
        )
        self.overlay_hotkey = GlobalOverlayHotkey(self.toggle_overlay)

    def _install_notifications(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        self._tray_icon.setToolTip("Jarvis Papa")
        self._tray_icon.messageClicked.connect(self._show_from_notification)
        self._tray_icon.show()
        self.proactive_timer = QTimer(self)
        self.proactive_timer.setInterval(5000)
        self.proactive_timer.timeout.connect(self._poll_proactive_events)
        self.proactive_timer.start()
        QTimer.singleShot(1200, self._poll_proactive_events)

    def _show_from_notification(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _poll_proactive_events(self) -> None:
        if self._tray_icon is None or self._proactive_poll_busy:
            return
        self._proactive_poll_busy = True
        self._worker(
            lambda: self.api.request(
                "GET",
                f"/api/intelligence/events?after={self.last_proactive_event}",
                timeout=3,
            ),
            self._proactive_events,
            on_error=self._proactive_events_failed,
        )

    def _proactive_events_failed(self, _message: str) -> None:
        self._proactive_poll_busy = False

    def _proactive_events(self, payload: dict[str, object]) -> None:
        self._proactive_poll_busy = False
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        for event in events:
            if not isinstance(event, dict):
                continue
            self.last_proactive_event = max(
                self.last_proactive_event,
                int(event.get("event_id") or 0),
            )
            level = str(event.get("level") or "normal").casefold()
            if level not in {"urgent", "important"} or self._tray_icon is None:
                continue
            title = str(event.get("title") or "Jarvis")[:180]
            detail = str(event.get("detail") or "Une information importante demande ton attention.")[:600]
            self._tray_icon.showMessage(title, detail)

    def toggle_overlay(self) -> None:
        self.overlay.toggle()

    def _overlay_query(self, text: str) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.chat_input.setText(text)
        self.send_chat()

    def open_memory_center(self) -> None:
        if self._memory_dialog is None:
            self._memory_dialog = MemoryCenterDialog(self)
            self._memory_dialog.finished.connect(self._memory_dialog_closed)
        self._memory_dialog.show()
        self._memory_dialog.raise_()
        self._memory_dialog.activateWindow()
        self._memory_dialog.refresh()

    def _memory_dialog_closed(self, _result: int) -> None:
        self._memory_dialog = None

    def create_backup(self) -> None:
        self.begin_activity("Je crée une sauvegarde locale de mes données durables.", speak=False)
        self._worker(
            lambda: self.api.request("POST", "/api/maintenance/backups", payload={}, timeout=15),
            self._backup_created,
        )

    def _backup_created(self, result: dict[str, object]) -> None:
        detail = str(result.get("detail") or "Sauvegarde terminée.")
        if bool(result.get("ok")):
            self.finish_activity(detail, speak=False)
        else:
            self.finish_activity(detail, success=False, speak=False)

    def configure_startup(self) -> None:
        self.begin_activity("Je vérifie le démarrage automatique de Jarvis.", speak=False)
        self._worker(
            lambda: self.api.request("GET", "/api/maintenance/status", timeout=4),
            self._startup_status_ready,
        )

    def _startup_status_ready(self, status: dict[str, object]) -> None:
        startup = status.get("startup") if isinstance(status.get("startup"), dict) else {}
        if not bool(startup.get("ok")):
            self.finish_activity(
                str(startup.get("detail") or "Le démarrage automatique n'est pas disponible."),
                success=False,
                speak=False,
            )
            return
        enabled = not bool(startup.get("enabled"))
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/maintenance/startup/plan",
                payload={"enabled": enabled},
                timeout=4,
            ),
            partial(self._startup_plan_ready, enabled),
        )

    def _startup_plan_ready(self, enabled: bool, plan: dict[str, object]) -> None:
        if not bool(plan.get("ok")):
            self.finish_activity("Je n'ai pas pu préparer ce changement.", success=False, speak=False)
            return
        action_key = str(plan.get("action_key") or "system.startup.configure")
        description = str(plan.get("description") or "Modifier le démarrage automatique.")
        binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {"enabled": enabled}
        token = self.authorize(action_key, description, binding)
        if not token:
            self.finish_activity("D'accord. Je ne change rien.", speak=False)
            return
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/maintenance/startup",
                payload={"enabled": enabled, "authorization_token": token},
                timeout=5,
            ),
            lambda result: self.finish_activity(
                str(result.get("detail") or "Configuration terminée."),
                success=bool(result.get("ok")),
                speak=False,
            ),
        )

    def emergency_stop(self) -> None:
        self.cancel_chat()
        self.begin_activity("J'arrête immédiatement les nouvelles actions de Jarvis.", speak=False)
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/intelligence/kill-switch",
                payload={"reason": "Arrêt immédiat demandé depuis l'interface."},
                timeout=3,
            ),
            self._emergency_stop_result,
            on_error=lambda _message: self.finish_partial(
                "J'ai arrêté la conversation et la voix, mais je n'ai pas pu confirmer le verrou global."
            ),
        )

    def _emergency_stop_result(self, result: dict[str, object]) -> None:
        if bool(result.get("ok")):
            self.finish_activity(
                "Jarvis est arrêté pour les actions. Tu peux toujours consulter les informations.",
                speak=False,
            )
        else:
            self.finish_partial(str(result.get("detail") or "Le verrou global n'est pas confirmé."))

    def clear_emergency_stop(self) -> None:
        self._worker(
            lambda: self.api.request("GET", "/api/intelligence/kill-switch/clear-plan", timeout=3),
            self._clear_stop_plan,
        )

    def _clear_stop_plan(self, plan: dict[str, object]) -> None:
        if not bool(plan.get("ok")):
            self._task_failed("Je ne peux pas préparer la réactivation.")
            return
        description = str(plan.get("description") or "Réactiver les actions de Jarvis.")
        binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
        token = self.authorize(
            str(plan.get("action_key") or "jarvis.kill_switch.clear"),
            description,
            binding,
        )
        if not token:
            return
        self._worker(
            lambda: self.api.request(
                "POST",
                "/api/intelligence/kill-switch/clear",
                payload={"authorization_token": token},
                timeout=4,
            ),
            lambda result: self.finish_activity(
                str(result.get("detail") or "Jarvis a été réactivé."),
                success=bool(result.get("ok")),
            ),
        )

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

    def closeEvent(self, event: QCloseEvent) -> None:
        self.overlay_hotkey.close()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        super().closeEvent(event)


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

    recovery = session_recovery.begin()
    recovery_backup = None
    if bool(recovery.get("previous_unclean")):
        recovery_backup = backup_manager.create("crash-recovery")

    backend = BackendService()
    if not backend.start():
        session_recovery.end()
        QMessageBox.critical(
            None,
            "Jarvis",
            "Jarvis n'a pas pu démarrer son service local. Redémarre l'application ou lance le diagnostic.",
        )
        lock.unlock()
        return

    try:
        window = JarvisProfessionalWindow()
        window.show()
        if bool(recovery.get("previous_unclean")):
            detail = "Le dernier arrêt de Jarvis n'était pas propre."
            if recovery_backup is not None and recovery_backup.ok:
                detail += " Une sauvegarde de sécurité a été créée avant de reprendre."
            QTimer.singleShot(
                400,
                lambda: QMessageBox.information(window, "Récupération Jarvis", detail),
            )
        exit_code = app.exec()
    finally:
        backend.stop()
        session_recovery.end()
        lock.unlock()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    run()
