from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser


@dataclass(frozen=True, slots=True)
class WebReadResult:
    ok: bool
    state: str
    url: str
    title: str = ""
    text: str = ""
    status_code: int | None = None
    content_type: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self._parts: list[str] = []
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "svg", "template"}:
            self._skip_depth += 1
        if lowered == "title" and self._skip_depth == 0:
            self._title_depth += 1
        if lowered in {"p", "div", "article", "section", "li", "br", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "title" and self._title_depth:
            self._title_depth -= 1
        if lowered in {"script", "style", "noscript", "svg", "template"} and self._skip_depth:
            self._skip_depth -= 1
        if lowered in {"p", "div", "article", "section", "li", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self._parts.append(cleaned + " ")
        if self._title_depth:
            self._title_parts.append(cleaned)

    def result(self, *, max_chars: int) -> tuple[str, str]:
        raw = "".join(self._parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        text = "\n".join(line for line in lines if line).strip()
        title = " ".join(self._title_parts).strip()
        return title[:500], text[:max_chars]


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not HttpReadService.is_public_url(newurl):
            raise urllib.error.URLError("redirect_to_private_or_invalid_url")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpReadService:
    """Read public text pages without launching a browser or trusting page instructions."""

    MAX_BYTES = 1_250_000
    MAX_TEXT_CHARS = 24_000
    USER_AGENT = "JarvisPapa/0.7 (+local personal assistant; read-only fetch)"

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_SafeRedirectHandler())

    @staticmethod
    def is_public_url(url: str) -> bool:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.rstrip(".").casefold()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            return False
        try:
            addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError:
            return False
        if not addresses:
            return False
        for address in addresses:
            raw_ip = address[4][0]
            try:
                ip = ipaddress.ip_address(raw_ip)
            except ValueError:
                return False
            if not ip.is_global:
                return False
        return True

    def read(self, url: str, *, timeout_seconds: float = 10.0) -> WebReadResult:
        url = url.strip()
        if not self.is_public_url(url):
            return WebReadResult(
                False,
                "failed",
                url,
                detail="Adresse Web privée, locale ou invalide bloquée.",
            )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.1",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=max(1.0, min(timeout_seconds, 20.0))) as response:
                final_url = response.geturl()
                if not self.is_public_url(final_url):
                    return WebReadResult(
                        False,
                        "failed",
                        url,
                        detail="Redirection vers une adresse privée ou locale bloquée.",
                    )
                status = int(getattr(response, "status", 200) or 200)
                content_type = str(response.headers.get_content_type() or "").casefold()
                allowed = content_type in {
                    "text/html",
                    "text/plain",
                    "application/xhtml+xml",
                }
                if not allowed:
                    return WebReadResult(
                        False,
                        "failed",
                        final_url,
                        status_code=status,
                        content_type=content_type,
                        detail="Cette ressource n'est pas une page texte lisible directement.",
                    )
                raw = response.read(self.MAX_BYTES + 1)
                if len(raw) > self.MAX_BYTES:
                    raw = raw[: self.MAX_BYTES]
                    state = "partial"
                else:
                    state = "success"
                charset = response.headers.get_content_charset() or "utf-8"
                decoded = raw.decode(charset, errors="replace")
                if content_type == "text/plain":
                    title = ""
                    text = "\n".join(
                        " ".join(line.split()) for line in decoded.splitlines() if line.strip()
                    )[: self.MAX_TEXT_CHARS]
                else:
                    parser = _TextExtractor()
                    parser.feed(decoded)
                    title, text = parser.result(max_chars=self.MAX_TEXT_CHARS)
                if not text:
                    return WebReadResult(
                        False,
                        "failed",
                        final_url,
                        title=title,
                        status_code=status,
                        content_type=content_type,
                        detail="La page ne contient pas de texte exploitable.",
                    )
                detail = "Page lue par requête HTTP, sans navigateur interactif."
                if state == "partial":
                    detail = "Page volumineuse : seule une portion bornée a été lue par HTTP."
                return WebReadResult(
                    True,
                    state,
                    final_url,
                    title=title,
                    text=text,
                    status_code=status,
                    content_type=content_type,
                    detail=detail,
                )
        except urllib.error.HTTPError as exc:
            return WebReadResult(
                False,
                "failed",
                url,
                status_code=int(exc.code),
                detail=f"Le site a répondu avec l'erreur HTTP {exc.code}.",
            )
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            return WebReadResult(
                False,
                "failed",
                url,
                detail=f"Lecture Web impossible ({type(exc).__name__}).",
            )


web_read_service = HttpReadService()
