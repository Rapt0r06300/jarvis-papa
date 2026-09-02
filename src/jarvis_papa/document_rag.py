from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree

from jarvis_papa.config import settings

_TOKEN = re.compile(r"[\wÀ-ÿ-]{2,}", re.UNICODE)
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".eml"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class DocumentHit:
    path: str
    name: str
    location: str
    snippet: str
    score: float
    modified_at: float
    extractor: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DocumentRAG:
    """Bounded local knowledge index with explicit provenance.

    Extracted text remains on the local machine. Results are data, never system
    instructions, and are intended to be wrapped as untrusted tool output before
    they are returned to a model.
    """

    MAX_FILE_BYTES = 30 * 1024 * 1024
    MAX_FILES_PER_INDEX = 500
    CHUNK_CHARS = 1400
    CHUNK_OVERLAP = 180

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "document-rag.sqlite3")
        self._init_db()

    def index(self, *, max_files: int = 250) -> dict[str, object]:
        started = time.monotonic()
        candidates = self._candidate_files(max_files)
        indexed = 0
        skipped = 0
        chunks = 0
        for file_path in candidates:
            try:
                stat = file_path.stat()
            except OSError:
                skipped += 1
                continue
            if stat.st_size <= 0 or stat.st_size > self.MAX_FILE_BYTES:
                skipped += 1
                continue
            fingerprint = self._fingerprint(file_path, stat.st_mtime, stat.st_size)
            if self._already_current(file_path, fingerprint):
                continue
            extracted = self._extract(file_path)
            if not extracted:
                skipped += 1
                continue
            self._replace_document(file_path, fingerprint, stat.st_mtime, stat.st_size, extracted)
            indexed += 1
            chunks += sum(len(self._chunks(text)) for _, text, _ in extracted)
        return {
            "ok": True,
            "state": "success",
            "indexed_files": indexed,
            "candidate_files": len(candidates),
            "skipped_files": skipped,
            "chunks_written": chunks,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "detail": f"Index documentaire local prêt : {indexed} fichier(s) actualisé(s).",
        }

    def search(self, query: str, *, limit: int = 6, refresh: bool = True) -> dict[str, object]:
        clean_query = " ".join(str(query).split()).strip()
        if not clean_query:
            return {"ok": False, "state": "failed", "detail": "Recherche documentaire vide."}
        if refresh:
            self.index(max_files=220)
        tokens = self._tokens(clean_query)
        if not tokens:
            return {"ok": True, "state": "success", "results": [], "detail": "Aucun terme exploitable."}
        rows = self._recent_chunks(1800)
        scored: list[tuple[float, sqlite3.Row]] = []
        folded_query = clean_query.casefold()
        for row in rows:
            body = str(row["text"])
            haystack = f"{row['name']} {row['location']} {body}"
            hay_tokens = self._tokens(haystack)
            overlap = len(tokens & hay_tokens)
            if overlap <= 0:
                continue
            score = overlap / max(1, len(tokens))
            if folded_query in haystack.casefold():
                score += 0.5
            name_tokens = self._tokens(str(row["name"]))
            score += len(tokens & name_tokens) * 0.18
            score += min(float(row["modified_at"]) / max(time.time(), 1.0), 1.0) * 0.03
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: max(1, min(int(limit), 12))]
        hits = [
            DocumentHit(
                path=str(row["path"]),
                name=str(row["name"]),
                location=str(row["location"]),
                snippet=self._snippet(str(row["text"]), tokens),
                score=round(score, 4),
                modified_at=float(row["modified_at"]),
                extractor=str(row["extractor"]),
            )
            for score, row in selected
        ]
        return {
            "ok": True,
            "state": "success",
            "query": clean_query,
            "results": [hit.to_dict() for hit in hits],
            "detail": (
                f"{len(hits)} passage(s) documentaire(s) trouvé(s) avec provenance locale."
                if hits
                else "Aucun passage documentaire pertinent n'a été trouvé."
            ),
        }

    def status(self) -> dict[str, object]:
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                documents = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
                chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        except (OSError, sqlite3.Error):
            documents = 0
            chunks = 0
        return {
            "available": True,
            "documents": documents,
            "chunks": chunks,
            "local_only": True,
            "provenance": True,
            "image_ocr": "metadata_only_until_local_ocr_available",
        }

    def _candidate_files(self, max_files: int) -> list[Path]:
        allowed = {suffix.casefold() for suffix in settings.file_allowed_extensions}
        output: list[Path] = []
        seen: set[Path] = set()
        for raw_root in settings.file_search_roots:
            root = Path(raw_root).expanduser()
            if not root.is_dir():
                continue
            try:
                iterator = root.rglob("*")
                for item in iterator:
                    if len(output) >= min(max_files, self.MAX_FILES_PER_INDEX):
                        return output
                    try:
                        resolved = item.resolve()
                    except OSError:
                        continue
                    if resolved in seen or not resolved.is_file():
                        continue
                    if resolved.suffix.casefold() not in allowed:
                        continue
                    seen.add(resolved)
                    output.append(resolved)
            except OSError:
                continue
        output.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
        return output[: min(max_files, self.MAX_FILES_PER_INDEX)]

    def _extract(self, path: Path) -> list[tuple[str, str, str]]:
        suffix = path.suffix.casefold()
        if suffix in _TEXT_EXTENSIONS:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return []
            return [("document", text[:300_000], "text")]
        if suffix == ".pdf":
            return self._extract_pdf(path)
        if suffix == ".docx":
            return self._extract_docx(path)
        if suffix == ".xlsx":
            return self._extract_xlsx(path)
        if suffix in _IMAGE_EXTENSIONS:
            # No cloud OCR and no hidden dependency. Filename/metadata still make scans discoverable.
            description = f"Image ou scan local : {path.stem.replace('_', ' ').replace('-', ' ')}"
            return [("image", description, "image_metadata")]
        return []

    @staticmethod
    def _extract_pdf(path: Path) -> list[tuple[str, str, str]]:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
        except (ImportError, OSError, ValueError):
            return []
        output: list[tuple[str, str, str]] = []
        for index, page in enumerate(reader.pages[:300], start=1):
            try:
                text = page.extract_text() or ""
            except (KeyError, TypeError, ValueError):
                text = ""
            if text.strip():
                output.append((f"page {index}", text[:100_000], "pdf"))
        return output

    @staticmethod
    def _extract_docx(path: Path) -> list[tuple[str, str, str]]:
        try:
            with zipfile.ZipFile(path) as archive:
                data = archive.read("word/document.xml")
        except (OSError, KeyError, zipfile.BadZipFile):
            return []
        try:
            root = ElementTree.fromstring(data)
        except ElementTree.ParseError:
            return []
        text = " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
        return [("document", text[:300_000], "docx")] if text.strip() else []

    @staticmethod
    def _extract_xlsx(path: Path) -> list[tuple[str, str, str]]:
        try:
            with zipfile.ZipFile(path) as archive:
                shared: list[str] = []
                try:
                    shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared = [
                        " ".join(node.text or "" for node in item.iter() if node.tag.endswith("}t"))
                        for item in shared_root
                    ]
                except (KeyError, ElementTree.ParseError):
                    shared = []
                output: list[tuple[str, str, str]] = []
                sheets = sorted(
                    name
                    for name in archive.namelist()
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                )
                for sheet_index, sheet_name in enumerate(sheets[:50], start=1):
                    try:
                        root = ElementTree.fromstring(archive.read(sheet_name))
                    except (KeyError, ElementTree.ParseError):
                        continue
                    values: list[str] = []
                    for cell in (node for node in root.iter() if node.tag.endswith("}c")):
                        cell_type = cell.attrib.get("t")
                        value_node = next((node for node in cell if node.tag.endswith("}v")), None)
                        if value_node is None or value_node.text is None:
                            continue
                        value = value_node.text
                        if cell_type == "s":
                            try:
                                value = shared[int(value)]
                            except (IndexError, TypeError, ValueError):
                                pass
                        values.append(value)
                    text = " | ".join(values)
                    if text.strip():
                        output.append((f"feuille {sheet_index}", text[:180_000], "xlsx"))
                return output
        except (OSError, zipfile.BadZipFile):
            return []

    def _replace_document(
        self,
        path: Path,
        fingerprint: str,
        modified_at: float,
        size: int,
        sections: list[tuple[str, str, str]],
    ) -> None:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("DELETE FROM chunks WHERE path=?", (str(path),))
            connection.execute("DELETE FROM documents WHERE path=?", (str(path),))
            connection.execute(
                "INSERT INTO documents(path, name, fingerprint, modified_at, size) VALUES (?, ?, ?, ?, ?)",
                (str(path), path.name, fingerprint, modified_at, size),
            )
            for location, text, extractor in sections:
                for index, chunk in enumerate(self._chunks(text)):
                    connection.execute(
                        """
                        INSERT INTO chunks(path, name, location, chunk_index, text, extractor, modified_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (str(path), path.name, location, index, chunk, extractor, modified_at),
                    )

    def _already_current(self, path: Path, fingerprint: str) -> bool:
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                row = connection.execute(
                    "SELECT fingerprint FROM documents WHERE path=? LIMIT 1", (str(path),)
                ).fetchone()
        except sqlite3.Error:
            return False
        return bool(row and row[0] == fingerprint)

    def _recent_chunks(self, limit: int) -> list[sqlite3.Row]:
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT path, name, location, text, extractor, modified_at FROM chunks "
                "ORDER BY modified_at DESC LIMIT ?",
                (max(1, min(limit, 5000)),),
            ).fetchall()

    @classmethod
    def _chunks(cls, text: str) -> list[str]:
        clean = re.sub(r"\s+", " ", str(text)).strip()
        if not clean:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + cls.CHUNK_CHARS)
            chunk = clean[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(clean):
                break
            start = max(start + 1, end - cls.CHUNK_OVERLAP)
        return chunks[:500]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.casefold() for token in _TOKEN.findall(text)}

    @staticmethod
    def _snippet(text: str, query_tokens: set[str]) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        folded = clean.casefold()
        positions = [folded.find(token) for token in query_tokens if folded.find(token) >= 0]
        start = max(0, min(positions) - 180) if positions else 0
        snippet = clean[start : start + 620]
        return ("…" if start else "") + snippet + ("…" if start + 620 < len(clean) else "")

    @staticmethod
    def _fingerprint(path: Path, modified_at: float, size: int) -> str:
        raw = f"{path}|{modified_at:.6f}|{size}".encode("utf-8", errors="ignore")
        return hashlib.sha256(raw).hexdigest()

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents(
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    modified_at REAL NOT NULL,
                    size INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    extractor TEXT NOT NULL,
                    modified_at REAL NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)")


document_rag = DocumentRAG()
