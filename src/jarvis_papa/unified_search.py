from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

from jarvis_papa.knowledge import local_document_rag
from jarvis_papa.memory_semantic import semantic_memory_store
from jarvis_papa.situation_store import situation_store
from jarvis_papa.situations import SearchResult


@dataclass(frozen=True, slots=True)
class UnifiedSearchHit:
    kind: str
    object_id: str
    title: str
    snippet: str
    score: float
    provenance: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["provenance"] = list(self.provenance)
        return payload


SituationSearch = Callable[[str, int], list[SearchResult]]
DocumentSearch = Callable[[str, int], list[object]]
MemorySearch = Callable[[str, int], list[object]]


class UnifiedSearch:
    """Additive search facade: situations participate without replacing legacy search."""

    def __init__(
        self,
        *,
        situation_search: SituationSearch | None = None,
        document_search: DocumentSearch | None = None,
        memory_search: MemorySearch | None = None,
    ) -> None:
        self._situations = situation_search or self._search_situations
        self._documents = document_search or self._search_documents
        self._memories = memory_search or self._search_memories

    def search(self, query: str, *, limit: int = 12) -> list[UnifiedSearchHit]:
        clean = " ".join(str(query).split()).strip()
        if not clean:
            return []
        per_source = max(2, min(int(limit), 10))
        hits: list[UnifiedSearchHit] = []
        for item in self._situations(clean, per_source):
            hits.append(
                UnifiedSearchHit(
                    item.result_type,
                    item.object_id,
                    item.title,
                    item.snippet,
                    item.score + 0.05,
                    item.provenance,
                )
            )
        for item in self._documents(clean, per_source):
            path = str(getattr(item, "path", ""))
            name = str(getattr(item, "name", "Document"))
            provenance = str(getattr(item, "provenance", name))
            hits.append(
                UnifiedSearchHit(
                    "document",
                    path or name,
                    name,
                    str(getattr(item, "excerpt", ""))[:1200],
                    float(getattr(item, "score", 0.0)),
                    (provenance,),
                )
            )
        for item in self._memories(clean, per_source):
            category = str(getattr(item, "category", "memory"))
            key = str(getattr(item, "key", "souvenir"))
            provenance = str(getattr(item, "provenance", "memory"))
            confidence = float(getattr(item, "confidence", 0.0))
            hits.append(
                UnifiedSearchHit(
                    "memory",
                    f"{category}:{key}",
                    key,
                    str(getattr(item, "value", ""))[:1200],
                    max(0.0, min(confidence, 1.0)) * 0.8,
                    (provenance,),
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: max(1, min(int(limit), 50))]

    @staticmethod
    def _search_situations(query: str, limit: int) -> list[SearchResult]:
        return situation_store.search(query, limit=limit)

    @staticmethod
    def _search_documents(query: str, limit: int) -> list[object]:
        return list(local_document_rag.search(query, limit=limit))

    @staticmethod
    def _search_memories(query: str, limit: int) -> list[object]:
        return list(semantic_memory_store.recall(query, limit=limit))


unified_search = UnifiedSearch()
