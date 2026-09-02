from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.document_rag import document_rag
from jarvis_papa.files import is_allowed_document

_PAGE = re.compile(r"^page\s+(\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DocumentHit:
    path: str
    name: str
    page: int | None
    ordinal: int
    excerpt: str
    score: float
    provenance: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LocalDocumentRAG:
    """Compatibility facade over Jarvis' persistent local document index.

    Existing callers keep the historical ``DocumentHit`` contract while the
    canonical engine now provides incremental indexing, richer formats and
    explicit provenance. No document content leaves the local machine.
    """

    def search(self, query: str, *, limit: int = 6) -> list[DocumentHit]:
        result = document_rag.search(query, limit=limit, refresh=True)
        raw_hits = result.get("results") if isinstance(result.get("results"), list) else []
        output: list[DocumentHit] = []
        for ordinal, item in enumerate(raw_hits, start=1):
            if not isinstance(item, dict):
                continue
            location = str(item.get("location") or "document")
            match = _PAGE.match(location)
            page = int(match.group(1)) if match else None
            name = str(item.get("name") or Path(str(item.get("path") or "document")).name)
            output.append(
                DocumentHit(
                    path=str(item.get("path") or ""),
                    name=name,
                    page=page,
                    ordinal=ordinal,
                    excerpt=str(item.get("snippet") or "")[:1800],
                    score=float(item.get("score") or 0.0),
                    provenance=f"{name}, {location}",
                )
            )
        return output

    def read_file(self, raw_path: str, *, max_chunks: int = 12) -> list[DocumentHit]:
        path = Path(raw_path).expanduser()
        if not is_allowed_document(path):
            return []
        # Index refresh makes the file available without mutating the source.
        document_rag.index(max_files=500)
        result = document_rag.search(path.stem, limit=max_chunks, refresh=False)
        raw_hits = result.get("results") if isinstance(result.get("results"), list) else []
        output: list[DocumentHit] = []
        expected = str(path.resolve())
        for ordinal, item in enumerate(raw_hits, start=1):
            if not isinstance(item, dict) or str(item.get("path") or "") != expected:
                continue
            location = str(item.get("location") or "document")
            match = _PAGE.match(location)
            page = int(match.group(1)) if match else None
            output.append(
                DocumentHit(
                    path=expected,
                    name=path.name,
                    page=page,
                    ordinal=ordinal,
                    excerpt=str(item.get("snippet") or "")[:1800],
                    score=float(item.get("score") or 1.0),
                    provenance=f"{path.name}, {location}",
                )
            )
        return output[: max(1, min(int(max_chunks), 30))]

    def status(self) -> dict[str, object]:
        return document_rag.status()


local_document_rag = LocalDocumentRAG()
