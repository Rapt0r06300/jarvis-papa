from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    rank: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchResponse:
    ok: bool
    query: str
    results: tuple[SearchResult, ...]
    detail: str
    duration_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "query": self.query,
            "results": [item.to_dict() for item in self.results],
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


class _DuckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": values.get("href", ""), "snippet": ""}
            self._capture = "title"
        elif tag in {"a", "div"} and "result__snippet" in classes and self._current is not None:
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a" and self._current is not None:
            self._capture = None
            self.results.append(self._current)
        elif self._capture == "snippet" and tag in {"a", "div"}:
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._current is None or self._capture is None:
            return
        key = self._capture
        self._current[key] = (self._current.get(key, "") + " " + data).strip()


class WebSearchService:
    """Small HTTP search layer distinct from browser automation.

    SEARCH finds candidate sources. Reading a chosen source remains a separate
    operation so Jarvis never claims that a page was read merely because it
    appeared in search results.
    """

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = "JarvisPapa/0.7 (+local personal assistant)"

    def search(self, query: str, *, limit: int = 6, timeout: float = 8.0) -> SearchResponse:
        started = time.monotonic()
        query = " ".join(query.split()).strip()[:500]
        if not query:
            return SearchResponse(False, "", (), "Recherche vide.", 0.0)
        limit = max(1, min(int(limit), 10))
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        request = urllib.request.Request(
            self.SEARCH_URL,
            data=data,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(1_500_000).decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError) as exc:
            return SearchResponse(
                False,
                query,
                (),
                f"La recherche Internet n'a pas répondu ({type(exc).__name__}).",
                round((time.monotonic() - started) * 1000, 1),
            )

        parser = _DuckParser()
        try:
            parser.feed(raw)
        except Exception:
            parser.results = []

        cleaned: list[SearchResult] = []
        seen: set[str] = set()
        for item in parser.results:
            target = self._clean_target(item.get("url", ""))
            title = self._clean_text(item.get("title", ""))
            snippet = self._clean_text(item.get("snippet", ""))
            if not target or not title or target in seen:
                continue
            seen.add(target)
            cleaned.append(SearchResult(title, target, snippet[:500], len(cleaned) + 1))
            if len(cleaned) >= limit:
                break

        duration = round((time.monotonic() - started) * 1000, 1)
        if not cleaned:
            return SearchResponse(False, query, (), "Aucune source exploitable trouvée.", duration)
        return SearchResponse(True, query, tuple(cleaned), f"{len(cleaned)} source(s) trouvée(s).", duration)

    @staticmethod
    def _clean_target(raw_url: str) -> str:
        raw_url = html.unescape(raw_url).strip()
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.netloc.endswith("duckduckgo.com"):
            query = urllib.parse.parse_qs(parsed.query)
            target = query.get("uddg", [""])[0]
            if target:
                raw_url = urllib.parse.unquote(target)
                parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return urllib.parse.urlunparse(parsed._replace(fragment=""))

    @staticmethod
    def _clean_text(value: str) -> str:
        value = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
        return value


web_search_service = WebSearchService()
