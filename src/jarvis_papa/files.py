import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class FileResult:
    path: str
    name: str
    size: int | None = None
    modified: float | None = None
    source: str = "fallback"
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def expanded_search_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for root in settings.file_search_roots:
        path = Path(os.path.expandvars(os.path.expanduser(str(root))))
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def is_allowed_path(raw_path: str | Path, *, require_file: bool = False) -> bool:
    try:
        path = Path(raw_path).expanduser().resolve()
    except OSError:
        return False
    if require_file and not path.is_file():
        return False
    for root in expanded_search_roots():
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def is_allowed_document(raw_path: str | Path) -> bool:
    try:
        path = Path(raw_path).expanduser().resolve()
    except OSError:
        return False
    return (
        is_allowed_path(path, require_file=True)
        and path.suffix.casefold() in {item.casefold() for item in settings.file_allowed_extensions}
    )


class FileSearcher:
    def __init__(self) -> None:
        self._everything = shutil.which("es.exe") or shutil.which("es")

    @property
    def backend(self) -> str:
        return "everything" if self._everything else "fallback"

    def search(self, query: str, *, limit: int = 12) -> list[FileResult]:
        query = " ".join(query.split()).strip()
        if not query:
            return []
        requested = min(max(1, limit), 30)

        if self._everything:
            # Ask Everything for extra candidates because results outside Robert's approved
            # document roots are discarded before anything is returned to Jarvis.
            results = self._search_everything(query, limit=min(100, requested * 5))
            if results:
                return self._rank(results, query)[:requested]

        return self._search_fallback(query, limit=requested)

    def _search_everything(self, query: str, *, limit: int) -> list[FileResult]:
        command = [
            self._everything or "es.exe",
            "-json",
            "-n",
            str(limit),
            "-size",
            "-date-modified",
            query,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []

        if completed.returncode != 0 or not completed.stdout.strip():
            return []

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return []

        rows = payload.get("results", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []

        results: list[FileResult] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = (
                row.get("full_path_and_name")
                or row.get("filename")
                or row.get("path")
                or row.get("name")
            )
            if not isinstance(raw, str) or not raw:
                continue
            result_path = Path(raw)
            if not is_allowed_document(result_path):
                continue
            try:
                stat = result_path.stat()
            except OSError:
                stat = None
            results.append(
                FileResult(
                    path=str(result_path.resolve()),
                    name=result_path.name,
                    size=_safe_int(row.get("size")) if stat is None else stat.st_size,
                    modified=None if stat is None else stat.st_mtime,
                    source="everything",
                )
            )
        return results

    def _search_fallback(self, query: str, *, limit: int) -> list[FileResult]:
        tokens = [token.casefold() for token in query.split() if len(token.strip()) >= 2]
        if not tokens:
            return []

        started = time.monotonic()
        matches: list[FileResult] = []

        for root in expanded_search_roots():
            if not root.exists() or not root.is_dir():
                continue
            for candidate in _walk_files(root):
                if time.monotonic() - started > settings.file_search_timeout_seconds:
                    break
                if candidate.suffix.casefold() not in {
                    item.casefold() for item in settings.file_allowed_extensions
                }:
                    continue
                name = candidate.name.casefold()
                matched = sum(1 for token in tokens if token in name)
                if matched == 0:
                    continue
                try:
                    stat = candidate.stat()
                    modified = stat.st_mtime
                    size = stat.st_size
                except OSError:
                    modified = 0.0
                    size = None
                matches.append(
                    FileResult(
                        path=str(candidate.resolve()),
                        name=candidate.name,
                        size=size,
                        modified=modified or None,
                        source="fallback",
                    )
                )
            if time.monotonic() - started > settings.file_search_timeout_seconds:
                break

        return self._rank(matches, query)[:limit]

    @staticmethod
    def _rank(results: list[FileResult], query: str) -> list[FileResult]:
        tokens = [token.casefold() for token in query.split() if len(token) >= 2]
        phrase = query.casefold()
        now = time.time()
        ranked: list[FileResult] = []
        for item in results:
            name = item.name.casefold()
            matched = sum(1 for token in tokens if token in name)
            score = matched * 10.0
            if phrase and phrase in name:
                score += 20.0
            if item.modified:
                age_days = max(0.0, (now - item.modified) / 86400)
                score += max(0.0, 5.0 - min(5.0, age_days / 90))
            ranked.append(
                FileResult(
                    path=item.path,
                    name=item.name,
                    size=item.size,
                    modified=item.modified,
                    source=item.source,
                    score=round(score, 2),
                )
            )
        ranked.sort(key=lambda item: (item.score, item.modified or 0.0), reverse=True)
        return ranked


def _walk_files(root: Path):
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                    elif entry.is_dir(follow_symlinks=False):
                        yield from _walk_files(Path(entry.path))
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        return


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


file_searcher = FileSearcher()
