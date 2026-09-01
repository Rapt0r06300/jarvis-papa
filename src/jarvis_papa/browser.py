import importlib.util
import ipaddress
import socket
import time
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
    """Playwright-backed browser automation with private-network isolation."""

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("playwright") is not None

    @staticmethod
    def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    @classmethod
    def _validate_public_url(cls, raw_url: str, *, resolve_dns: bool = True) -> str:
        cleaned = raw_url.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Seules les URL HTTP/HTTPS publiques sont autorisées.")
        if parsed.username or parsed.password:
            raise ValueError("Les URL contenant des identifiants sont refusées.")
        host = parsed.hostname.casefold()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("Les adresses locales ne sont pas accessibles par le navigateur agentique.")

        try:
            direct_address = ipaddress.ip_address(host)
        except ValueError:
            direct_address = None
        if direct_address is not None:
            if not cls._is_public_address(direct_address):
                raise ValueError("Les adresses réseau privées ne sont pas autorisées.")
            return cleaned

        if resolve_dns:
            try:
                resolved = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            except OSError as exc:
                raise ValueError("Le nom de domaine ne peut pas être vérifié.") from exc
            addresses = {
                ipaddress.ip_address(item[4][0].split("%")[0])
                for item in resolved
                if item and item[4]
            }
            if not addresses or any(not cls._is_public_address(address) for address in addresses):
                raise ValueError("Ce domaine pointe vers une adresse réseau non publique.")
        return cleaned

    @classmethod
    def _route_request(cls, route) -> None:
        try:
            cls._validate_public_url(route.request.url, resolve_dns=True)
        except (ValueError, OSError):
            route.abort()
            return
        route.continue_()

    def read_url(self, raw_url: str) -> BrowserResult:
        try:
            url = self._validate_public_url(raw_url)
        except ValueError as exc:
            return BrowserResult(False, "read", raw_url, str(exc))
        if not self.available:
            return BrowserResult(False, "read", url, "Playwright n'est pas installé.")

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                context.route("**/*", self._route_request)
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.browser_timeout_seconds * 1000),
                )
                final_url = self._validate_public_url(page.url)
                title = page.title()[:300]
                text = page.locator("body").inner_text(timeout=5000)[: settings.browser_max_text_chars]
                links: list[dict[str, str]] = []
                for anchor in page.locator("a").all()[:50]:
                    label = (anchor.inner_text(timeout=1000) or "").strip()
                    href = anchor.get_attribute("href") or ""
                    if label and href:
                        links.append({"text": label[:180], "href": href[:1500]})
                browser.close()
        except (PlaywrightError, ValueError, OSError) as exc:
            return BrowserResult(False, "read", url, f"Lecture web impossible : {exc}")

        return BrowserResult(
            True,
            "read",
            final_url,
            "Page publique lue avec Playwright.",
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
        output: Path | None = None
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(accept_downloads=True)
                context.route("**/*", self._route_request)
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
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
                extension = Path(filename).suffix.casefold()
                if extension not in {item.casefold() for item in settings.browser_download_extensions}:
                    raise ValueError("Ce type de fichier n'est pas autorisé au téléchargement.")
                output = self._unique_destination(destination, filename)
                download.save_as(str(output))
                size = output.stat().st_size
                if size > settings.browser_download_max_bytes:
                    output.unlink(missing_ok=True)
                    raise ValueError("Le fichier téléchargé dépasse la taille maximale autorisée.")
                browser.close()
        except (PlaywrightError, ValueError, OSError) as exc:
            if output is not None:
                output.unlink(missing_ok=True)
            return BrowserResult(False, "download", url, f"Téléchargement refusé ou impossible : {exc}")

        return BrowserResult(
            True,
            "download",
            url,
            "Téléchargement terminé et vérifié.",
            path=str(output.resolve()),
        )

    @staticmethod
    def _unique_destination(folder: Path, filename: str) -> Path:
        candidate = folder / filename
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        stamp = int(time.time())
        return folder / f"{stem}-{stamp}{suffix}"


browser_agent = BrowserAgent()
