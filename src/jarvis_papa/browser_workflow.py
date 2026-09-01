from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass

from jarvis_papa.browser import BrowserAgent
from jarvis_papa.config import settings

_SENSITIVE_FIELD = re.compile(
    r"password|passwd|mot de passe|pin|cvv|cvc|card|carte|iban|bic|secret|token",
    re.IGNORECASE,
)
_ALLOWED_ROLES = {"button", "link", "checkbox", "radio", "tab", "menuitem"}
_ALLOWED_STEPS = {
    "navigate",
    "fill",
    "select",
    "check",
    "uncheck",
    "click",
    "click_role",
    "wait_for_text",
    "wait_for_url",
}


@dataclass(frozen=True, slots=True)
class BrowserFormField:
    name: str
    label: str
    field_type: str
    required: bool
    disabled: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BrowserWorkflow:
    """Controlled Playwright workflows with explicit verification semantics."""

    def __init__(self) -> None:
        self._guard = BrowserAgent()

    def inspect(self, raw_url: str) -> dict[str, object]:
        try:
            url = self._guard._validate_public_url(raw_url)
        except ValueError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        if not self._guard.available:
            return {"ok": False, "state": "failed", "detail": "Playwright n'est pas disponible."}
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = self._guard._launch_browser(playwright)
                context = browser.new_context()
                context.route("**/*", self._guard._route_request)
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                fields: list[BrowserFormField] = []
                for element in page.locator("input, textarea, select").all()[:50]:
                    field_type = (
                        element.get_attribute("type")
                        or element.evaluate("el => el.tagName.toLowerCase()")
                        or "text"
                    ).lower()
                    name = element.get_attribute("name") or element.get_attribute("id") or ""
                    label = (
                        element.get_attribute("aria-label")
                        or element.get_attribute("placeholder")
                        or name
                    )
                    fields.append(
                        BrowserFormField(
                            name=name[:180],
                            label=label[:240],
                            field_type=field_type[:80],
                            required=bool(element.get_attribute("required") is not None),
                            disabled=bool(element.get_attribute("disabled") is not None),
                        )
                    )
                buttons = []
                for element in page.locator(
                    "button, input[type=submit], input[type=button]"
                ).all()[:40]:
                    text = (
                        element.inner_text(timeout=800)
                        or element.get_attribute("value")
                        or ""
                    ).strip()
                    if text:
                        buttons.append(text[:180])
                final_url = self._guard._validate_public_url(page.url)
                title = page.title()[:300]
                browser.close()
        except (PlaywrightError, ValueError, OSError) as exc:
            return {"ok": False, "state": "failed", "detail": f"Inspection impossible : {exc}"}
        return {
            "ok": True,
            "state": "success",
            "url": final_url,
            "title": title,
            "fields": [item.to_dict() for item in fields],
            "buttons": buttons,
            "detail": f"{len(fields)} champ(s) et {len(buttons)} action(s) détectés.",
        }

    def execute(
        self,
        *,
        raw_url: str,
        fields: dict[str, str],
        button_text: str,
        verify_text: str = "",
        session_name: str = "default",
    ) -> dict[str, object]:
        steps: list[dict[str, object]] = [
            {"action": "fill", "name": name, "value": value}
            for name, value in fields.items()
        ]
        steps.append({"action": "click", "text": button_text})
        return self.execute_steps(
            raw_url=raw_url,
            steps=steps,
            verify_text=verify_text,
            session_name=session_name,
        )

    def execute_steps(
        self,
        *,
        raw_url: str,
        steps: list[dict[str, object]],
        verify_text: str = "",
        session_name: str = "default",
    ) -> dict[str, object]:
        try:
            url = self._guard._validate_public_url(raw_url)
            clean_steps = self._validate_steps(steps)
        except ValueError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        if not self._guard.available:
            return {"ok": False, "state": "failed", "detail": "Playwright n'est pas disponible."}

        session = re.sub(r"[^a-zA-Z0-9_-]", "", session_name)[:40] or "default"
        profile = settings.runtime_dir / "browser-sessions" / session
        profile.mkdir(parents=True, exist_ok=True)
        evidence: list[dict[str, object]] = []
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                launch_args: dict[str, object] = {"headless": True}
                if sys.platform == "win32":
                    launch_args["channel"] = "msedge"
                try:
                    context = playwright.chromium.launch_persistent_context(
                        str(profile), **launch_args
                    )
                except PlaywrightError:
                    launch_args.pop("channel", None)
                    context = playwright.chromium.launch_persistent_context(
                        str(profile), **launch_args
                    )
                context.route("**/*", self._guard._route_request)
                page = context.pages[0] if context.pages else context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                self._guard._validate_public_url(page.url)
                for index, step in enumerate(clean_steps):
                    self._run_step(page, step, PlaywrightError)
                    current_url = self._guard._validate_public_url(page.url)
                    evidence.append(
                        {
                            "step": index + 1,
                            "action": step["action"],
                            "url": current_url,
                            "verified": step["action"] in {"wait_for_text", "wait_for_url"},
                        }
                    )
                final_url = self._guard._validate_public_url(page.url)
                title = page.title()[:300]
                body = page.locator("body").inner_text(timeout=5000)[:12000]
                context.close()
        except (PlaywrightError, ValueError, OSError) as exc:
            return {
                "ok": False,
                "state": "failed",
                "evidence": evidence,
                "detail": f"Workflow Web interrompu : {exc}",
            }

        verified = bool(verify_text and verify_text.casefold() in body.casefold())
        return {
            "ok": True,
            "state": "success" if verified else "partial",
            "verified": verified,
            "url": final_url,
            "title": title,
            "evidence": evidence,
            "detail": (
                "Le résultat final demandé a été vérifié sur la page."
                if verified
                else (
                    "Le parcours Web est terminé, mais Jarvis ne dispose pas d'une preuve "
                    "finale suffisante pour affirmer que la démarche métier a réussi."
                )
            ),
        }

    def _validate_steps(self, steps: list[dict[str, object]]) -> list[dict[str, object]]:
        if not 1 <= len(steps) <= 20:
            raise ValueError("Un workflow Web doit contenir entre 1 et 20 étapes.")
        clean: list[dict[str, object]] = []
        for raw in steps:
            if not isinstance(raw, dict):
                raise ValueError("Étape Web invalide.")
            action = str(raw.get("action") or "").strip().casefold()
            if action not in _ALLOWED_STEPS:
                raise ValueError(f"Étape Web non autorisée : {action or 'vide'}")
            step = dict(raw)
            step["action"] = action
            if action == "navigate":
                step["url"] = self._guard._validate_public_url(str(raw.get("url") or ""))
            elif action in {"fill", "select"}:
                name = str(raw.get("name") or "").strip()
                value = str(raw.get("value") or "")
                self._ensure_safe_field(name, value)
                if not name:
                    raise ValueError("Nom de champ manquant.")
                step["name"] = name[:180]
                step["value"] = value[:4000]
            elif action in {"check", "uncheck"}:
                name = str(raw.get("name") or "").strip()
                self._ensure_safe_field(name, "")
                if not name:
                    raise ValueError("Nom de case manquant.")
                step["name"] = name[:180]
            elif action == "click":
                text = str(raw.get("text") or "").strip()
                if not text:
                    raise ValueError("Texte du bouton ou lien manquant.")
                step["text"] = text[:300]
            elif action == "click_role":
                role = str(raw.get("role") or "").strip().casefold()
                name = str(raw.get("name") or "").strip()
                if role not in _ALLOWED_ROLES or not name:
                    raise ValueError("Rôle ou nom du contrôle Web invalide.")
                step["role"] = role
                step["name"] = name[:300]
            elif action == "wait_for_text":
                text = str(raw.get("text") or "").strip()
                if not text:
                    raise ValueError("Texte attendu manquant.")
                step["text"] = text[:500]
            elif action == "wait_for_url":
                expected = str(raw.get("contains") or "").strip()
                if not expected or len(expected) > 500:
                    raise ValueError("Critère d'URL attendu invalide.")
                step["contains"] = expected
            clean.append(step)
        return clean

    def _run_step(self, page, step: dict[str, object], playwright_error) -> None:
        action = str(step["action"])
        timeout = int(settings.browser_timeout_seconds * 1000)
        if action == "navigate":
            page.goto(
                str(step["url"]),
                wait_until="domcontentloaded",
                timeout=timeout,
            )
            return
        if action in {"fill", "select", "check", "uncheck"}:
            locator = self._named_locator(page, str(step["name"]))
            element_type = (locator.first.get_attribute("type") or "").casefold()
            if element_type in {"password", "file"}:
                raise ValueError("Champ sensible ou upload de fichier refusé.")
            if action == "fill":
                locator.first.fill(str(step["value"]))
            elif action == "select":
                locator.first.select_option(str(step["value"]))
            elif action == "check":
                locator.first.check()
            else:
                locator.first.uncheck()
            return
        if action == "click":
            locator = page.get_by_text(str(step["text"]), exact=False)
            self._require_unique(locator, "Le bouton ou lien demandé")
            locator.first.click(timeout=timeout)
            self._wait_after_click(page, playwright_error)
            return
        if action == "click_role":
            locator = page.get_by_role(str(step["role"]), name=str(step["name"]), exact=False)
            self._require_unique(locator, "Le contrôle demandé")
            locator.first.click(timeout=timeout)
            self._wait_after_click(page, playwright_error)
            return
        if action == "wait_for_text":
            locator = page.get_by_text(str(step["text"]), exact=False)
            if locator.count() < 1:
                locator.first.wait_for(state="visible", timeout=timeout)
            else:
                locator.first.wait_for(state="visible", timeout=timeout)
            return
        if action == "wait_for_url":
            expected = str(step["contains"])
            deadline_ms = min(timeout, 15000)
            page.wait_for_function(
                "expected => window.location.href.includes(expected)",
                arg=expected,
                timeout=deadline_ms,
            )
            return
        raise ValueError(f"Étape non prise en charge : {action}")

    def _named_locator(self, page, name: str):
        locator = page.locator(f'[name="{name}"]')
        if locator.count() != 1:
            locator = page.locator(f'#{name}')
        self._require_unique(locator, f"Le champ {name}")
        return locator

    @staticmethod
    def _require_unique(locator, label: str) -> None:
        if locator.count() != 1:
            raise ValueError(f"{label} est ambigu ou introuvable.")

    @staticmethod
    def _wait_after_click(page, playwright_error) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except playwright_error:
            pass

    @staticmethod
    def _ensure_safe_field(name: str, value: str) -> None:
        probe = f"{name} {value[:80]}"
        if _SENSITIVE_FIELD.search(probe):
            raise ValueError(
                "Jarvis refuse de saisir automatiquement un mot de passe, une donnée "
                "financière ou un secret."
            )


browser_workflow = BrowserWorkflow()
