from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.browser import BrowserAgent
from jarvis_papa.config import settings

_SENSITIVE_FIELD = re.compile(
    r"password|passwd|mot de passe|pin|cvv|cvc|card|carte|iban|bic|secret|token",
    re.IGNORECASE,
)


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
            url = self._guard._validate_public_url(raw_url)  # noqa: SLF001 - shared SSRF guard.
        except ValueError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        if not self._guard.available:
            return {"ok": False, "state": "failed", "detail": "Playwright n'est pas disponible."}
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = self._guard._launch_browser(playwright)  # noqa: SLF001
                context = browser.new_context()
                context.route("**/*", self._guard._route_request)  # noqa: SLF001
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                fields: list[BrowserFormField] = []
                for element in page.locator("input, textarea, select").all()[:50]:
                    field_type = (element.get_attribute("type") or element.evaluate("el => el.tagName.toLowerCase()") or "text").lower()
                    name = element.get_attribute("name") or element.get_attribute("id") or ""
                    label = element.get_attribute("aria-label") or element.get_attribute("placeholder") or name
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
                for element in page.locator("button, input[type=submit], input[type=button]").all()[:40]:
                    text = (element.inner_text(timeout=800) or element.get_attribute("value") or "").strip()
                    if text:
                        buttons.append(text[:180])
                final_url = self._guard._validate_public_url(page.url)  # noqa: SLF001
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
        try:
            url = self._guard._validate_public_url(raw_url)  # noqa: SLF001
        except ValueError as exc:
            return {"ok": False, "state": "failed", "detail": str(exc)}
        if not self._guard.available:
            return {"ok": False, "state": "failed", "detail": "Playwright n'est pas disponible."}
        for name, value in fields.items():
            probe = f"{name} {value[:80]}"
            if _SENSITIVE_FIELD.search(probe):
                return {
                    "ok": False,
                    "state": "failed",
                    "detail": "Jarvis refuse de saisir automatiquement un mot de passe ou une donnée financière sensible.",
                }
        if not button_text.strip():
            return {"ok": False, "state": "failed", "detail": "Bouton cible manquant."}
        session = re.sub(r"[^a-zA-Z0-9_-]", "", session_name)[:40] or "default"
        profile = settings.runtime_dir / "browser-sessions" / session
        profile.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                launch_args = {"headless": True}
                if sys.platform == "win32":
                    launch_args["channel"] = "msedge"
                try:
                    context = playwright.chromium.launch_persistent_context(str(profile), **launch_args)
                except PlaywrightError:
                    launch_args.pop("channel", None)
                    context = playwright.chromium.launch_persistent_context(str(profile), **launch_args)
                context.route("**/*", self._guard._route_request)  # noqa: SLF001
                page = context.pages[0] if context.pages else context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                for name, value in fields.items():
                    locator = page.locator(f'[name="{name}"]')
                    if locator.count() != 1:
                        locator = page.locator(f'#{name}')
                    if locator.count() != 1:
                        raise ValueError(f"Champ ambigu ou introuvable : {name}")
                    element_type = (locator.first.get_attribute("type") or "").casefold()
                    if element_type in {"password", "file"}:
                        raise ValueError("Champ sensible ou fichier refusé.")
                    locator.first.fill(str(value)[:4000])
                button = page.get_by_text(button_text, exact=False)
                if button.count() != 1:
                    raise ValueError("Le bouton demandé est ambigu ou introuvable.")
                button.first.click(timeout=int(settings.browser_timeout_seconds * 1000))
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PlaywrightError:
                    pass
                final_url = self._guard._validate_public_url(page.url)  # noqa: SLF001
                title = page.title()[:300]
                body = page.locator("body").inner_text(timeout=5000)[:12000]
                context.close()
        except (PlaywrightError, ValueError, OSError) as exc:
            return {"ok": False, "state": "failed", "detail": f"Interaction impossible : {exc}"}

        verified = bool(verify_text and verify_text.casefold() in body.casefold())
        return {
            "ok": True,
            "state": "success" if verified else "partial",
            "verified": verified,
            "url": final_url,
            "title": title,
            "detail": (
                "Le résultat demandé a été vérifié sur la page."
                if verified
                else "L'interaction a été effectuée, mais aucun critère suffisant ne permet d'affirmer que l'action métier a réussi."
            ),
        }


browser_workflow = BrowserWorkflow()
