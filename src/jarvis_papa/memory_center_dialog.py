from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class MemoryCenterDialog(QDialog):
    """Simple human-facing view of what Jarvis remembers."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Ce que Jarvis retient")
        self.resize(720, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Ce que Jarvis retient")
        title.setStyleSheet("font-size: 20px; font-weight: 650;")
        root.addWidget(title)

        explanation = QLabel(
            "Tu peux vérifier ce que Jarvis a mémorisé. Corriger ou oublier une information demande toujours deux confirmations."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        refresh = QPushButton("Actualiser")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)

        edit = QPushButton("Corriger")
        edit.clicked.connect(self.edit_selected)
        row.addWidget(edit)

        forget = QPushButton("Oublier")
        forget.clicked.connect(self.forget_selected)
        row.addWidget(forget)

        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        self.window._worker(
            lambda: self.window.api.request("GET", "/api/memory-center", timeout=5),
            self._loaded,
            on_error=lambda message: QMessageBox.warning(self, "Mémoire", message),
        )

    def _loaded(self, payload: dict[str, object]) -> None:
        memories = payload.get("memories") if isinstance(payload.get("memories"), list) else []
        procedures = payload.get("procedures") if isinstance(payload.get("procedures"), list) else []
        for memory in memories:
            if not isinstance(memory, dict):
                continue
            category = str(memory.get("category") or "information")
            key = str(memory.get("key") or "information")
            value = str(memory.get("value") or "")
            item = QListWidgetItem(f"{key}  —  {value}")
            item.setData(Qt.ItemDataRole.UserRole, {"kind": "memory", **memory})
            item.setToolTip(f"Catégorie : {category}")
            self.list.addItem(item)
        for procedure in procedures:
            if not isinstance(procedure, dict) or not bool(procedure.get("enabled", True)):
                continue
            summary = str(procedure.get("summary") or procedure.get("key") or "Procédure")
            item = QListWidgetItem(f"Habitude approuvée  —  {summary}")
            item.setData(Qt.ItemDataRole.UserRole, {"kind": "procedure", **procedure})
            self.list.addItem(item)
        if self.list.count() == 0:
            item = QListWidgetItem("Jarvis n'a encore rien mémorisé de durable.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)

    def _selected(self) -> dict[str, object] | None:
        item = self.list.currentItem()
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        return payload if isinstance(payload, dict) else None

    def edit_selected(self) -> None:
        selected = self._selected()
        if not selected or selected.get("kind") != "memory":
            QMessageBox.information(self, "Mémoire", "Choisis d'abord une information mémorisée.")
            return
        current = str(selected.get("value") or "")
        value, ok = QInputDialog.getText(
            self,
            "Corriger ce souvenir",
            "Quelle information Jarvis doit-il retenir ?",
            text=current,
        )
        if not ok or " ".join(value.split()).strip() == current:
            return
        category = str(selected.get("category") or "information")
        key = str(selected.get("key") or "information")
        payload = {"category": category, "key": key, "value": value}
        self.window._worker(
            lambda: self.window.api.request(
                "POST", "/api/memory-center/update/plan", payload=payload, timeout=5
            ),
            lambda plan: self._apply_update(plan, payload),
        )

    def _apply_update(self, plan: dict[str, object], payload: dict[str, object]) -> None:
        if not bool(plan.get("ok")):
            QMessageBox.warning(self, "Mémoire", "Cette correction n'est pas valide.")
            return
        binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
        description = str(plan.get("description") or "Corriger ce souvenir.")
        token = self.window.authorize("memory.update", description, binding)
        if not token:
            return
        body = {**payload, "authorization_token": token}
        self.window._worker(
            lambda: self.window.api.request(
                "POST", "/api/memory-center/update", payload=body, timeout=6
            ),
            self._mutation_result,
        )

    def forget_selected(self) -> None:
        selected = self._selected()
        if not selected:
            return
        if selected.get("kind") == "procedure":
            procedure_id = str(selected.get("id") or selected.get("procedure_id") or "")
            summary = str(selected.get("summary") or selected.get("key") or "")
            if not procedure_id:
                return
            payload = {"procedure_id": procedure_id, "summary": summary}
            self.window._worker(
                lambda: self.window.api.request(
                    "POST", "/api/memory-center/procedure/disable/plan", payload=payload, timeout=5
                ),
                lambda plan: self._disable_procedure(plan, payload),
            )
            return
        category = str(selected.get("category") or "information")
        key = str(selected.get("key") or "information")
        payload = {"category": category, "key": key, "value": ""}
        self.window._worker(
            lambda: self.window.api.request(
                "POST", "/api/memory-center/forget/plan", payload=payload, timeout=5
            ),
            lambda plan: self._apply_forget(plan, payload),
        )

    def _apply_forget(self, plan: dict[str, object], payload: dict[str, object]) -> None:
        binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
        description = str(plan.get("description") or "Oublier ce souvenir.")
        token = self.window.authorize("memory.forget", description, binding)
        if not token:
            return
        body = {**payload, "authorization_token": token}
        self.window._worker(
            lambda: self.window.api.request(
                "POST", "/api/memory-center/forget", payload=body, timeout=6
            ),
            self._mutation_result,
        )

    def _disable_procedure(self, plan: dict[str, object], payload: dict[str, object]) -> None:
        binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
        description = str(plan.get("description") or "Désactiver cette procédure.")
        token = self.window.authorize("memory.procedure.disable", description, binding)
        if not token:
            return
        body = {**payload, "authorization_token": token}
        self.window._worker(
            lambda: self.window.api.request(
                "POST", "/api/memory-center/procedure/disable", payload=body, timeout=6
            ),
            self._mutation_result,
        )

    def _mutation_result(self, result: dict[str, object]) -> None:
        detail = str(result.get("detail") or "Mémoire mise à jour.")
        if bool(result.get("ok")):
            QMessageBox.information(self, "Mémoire", detail)
            self.refresh()
        else:
            QMessageBox.warning(self, "Mémoire", detail)
