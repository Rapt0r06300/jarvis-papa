import importlib.util
import ipaddress
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class BrowserResult:
    ok: bool
    action: str
    url: str
    detail: str
    title: str = ""
    text: str = ""
    links: tuple[dict[str, str], ...] = ()
    path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BrowserAgent:
    """Playwright-backed browser automation for deliberate web tasks."""

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("playwright") is not None

    @staticmethod
    def _validate_public_url(raw_url: str) -> str:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Seules les URL HTTP/HTTPS sont autorisées.")
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("Les adresses locales ne sont pas accessibles par le navigateur agentique.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return raw_url.strip()
        if address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("Les adresses réseau privées ne sont pas autorisées.")
        return raw_url.strip()

    def read_url(self, raw_url: str) -> BrowserResult:
        try:
            url = self._validate_public_url(raw_url)
        except ValueError as exc:
            return BrowserResult(False, "read", raw_url, str(exc))
        if not self.available:
            return BrowserResult(False, "read", url, "Playwright n'est pas installé.")

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                title = page.title()
                text = page.locator("body").inner_text(timeout=5000)[: settings.browser_max_text_chars]
                links: list[dict[str, str]] = []
                for anchor in page.locator("a").all()[:50]:
                    label = (anchor.inner_text(timeout=1000) or "").strip()
                    href = anchor.get_attribute("href") or ""
                    if label and href:
                        links.append({"text": label[:180], "href": href[:1500]})
                browser.close()
        except Exception as exc:  # noqa: BLE001 - Playwright exposes many runtime exception types.
            return BrowserResult(False, "read", url, str(exc))

        return BrowserResult(
            True,
            "read",
            url,
            "Page lue avec Playwright.",
            title=title,
            text=text,
            links=tuple(links),
        )

    def download_by_text(self, raw_url: str, link_text: str) -> BrowserResult:
        try:
            url = self._validate_public_url(raw_url)
        except ValueError as exc:
            return BrowserResult(False, "download", raw_url, str(exc))
        if not self.available:
            return BrowserResult(False, "download", url, "Playwright n'est pas installé.")

        destination = settings.runtime_dir / "downloads"
        destination.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(accept_downloads=True)
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                target = page.get_by_text(link_text, exact=False).first
                with page.expect_download(timeout=int(settings.browser_timeout_seconds * 1000)) as pending:
                    target.click()
                download = pending.value
                filename = Path(download.suggested_filename).name
                output = destination / filename
                download.save_as(str(output))
                browser.close()
        except Exception as exc:  # noqa: BLE001 - Playwright exposes many runtime exception types.
            return BrowserResult(False, "download", url, str(exc))

        return BrowserResult(
            True,
            "download",
            url,
            "Téléchargement terminé.",
            path=str(output.resolve()),
        )


browser_agent = BrowserAgent()
