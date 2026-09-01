import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from jarvis_papa.config import settings
from jarvis_papa.files import is_allowed_document


@dataclass(frozen=True, slots=True)
class AttachmentLease:
    token: str
    path: Path
    name: str
    media_type: str
    expires_at: float
    size: int


class AttachmentBroker:
    """Short-lived one-use local file leases consumed by the Thunderbird extension."""

    def __init__(self) -> None:
        self._leases: dict[str, AttachmentLease] = {}
        self._lock = Lock()

    def register(self, raw_path: str | Path, ttl_seconds: int = 300) -> AttachmentLease:
        path = Path(raw_path).expanduser().resolve()
        if not is_allowed_document(path):
            raise PermissionError("Ce fichier n'est pas dans un dossier/document autorisé par Jarvis.")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise FileNotFoundError(path) from exc
        if size > settings.attachment_max_bytes:
            raise ValueError(
                f"Pièce jointe trop volumineuse ({size} octets, maximum {settings.attachment_max_bytes})."
            )
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        lease = AttachmentLease(
            token=uuid4().hex,
            path=path,
            name=path.name,
            media_type=media_type,
            expires_at=time.time() + max(30, min(ttl_seconds, 900)),
            size=size,
        )
        with self._lock:
            self._cleanup_locked()
            self._leases[lease.token] = lease
        return lease

    def consume(self, token: str) -> AttachmentLease | None:
        with self._lock:
            self._cleanup_locked()
            lease = self._leases.pop(token, None)
        if lease and lease.expires_at >= time.time() and lease.path.is_file():
            return lease
        return None

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [token for token, lease in self._leases.items() if lease.expires_at < now]
        for token in expired:
            self._leases.pop(token, None)


attachment_broker = AttachmentBroker()
