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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FileSearcher:
    def __init__(self) -> None:
        self._everything = shutil.which("es.exe") or shutil.which("es")

    @property
    def backend(self) -> str:
        return "everything" if self._everything else "fallback"

    def search(self, query: str, *, limit: int = 12) -> list[FileResult]:
        query = query.strip()
        if not query:
            return []

        if self._everything:
            results = self._search_everything(query, limit=limit)
            if results:
                return results

        return self._search_fallback(query, limit=limit)

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
            path = (
                row.get("full_path_and_name")
                or row.get("filename")
                or row.get("path")
                or row.get("name")
            )
            if not isinstance(path, str) or not path:
                continue

            result_path = Path(path)
            results.append(
                FileResult(
                    path=str(result_path),
                    name=result_path.name,
                    size=_safe_int(row.get("size")),
                    source="everything",
                )
            )
        return results[:limit]

    def _search_fallback(self, query: str, *, limit: int) -> list[FileResult]:
        tokens = [token.casefold() for token in query.split() if token.strip()]
        if not tokens:
            return []

        started = time.monotonic()
        matches: list[tuple[int, float, FileResult]] = []

        for root in settings.file_search_roots:
            path = Path(os.path.expandvars(os.path.expanduser(str(root))))
            if not path.exists() or not path.is_dir():
                continue

            for candidate in _walk_files(path):
                if time.monotonic() - started > settings.file_search_timeout_seconds:
                    break

                haystack = candidate.name.casefold()
                score = sum(1 for token in tokens if token in haystack)
                if score == 0:
                    continue

                try:
                    stat = candidate.stat()
                    modified = stat.st_mtime
                    size = stat.st_size
                except OSError:
                    modified = 0.0
                    size = None

                result = FileResult(
                    path=str(candidate),
                    name=candidate.name,
                    size=size,
                    modified=modified or None,
                    source="fallback",
                )
                matches.append((score, modified, result))

            if time.monotonic() - started > settings.file_search_timeout_seconds:
                break

        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in matches[:limit]]


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
