"""Ledger-first, idempotent publishing.

Posting is the one irreversible action in the pipeline. Every publisher follows the same contract:

1. Reserve the item in the ledger BEFORE any network call (atomic write).
2. Record each stage as it completes (uploading -> publishing -> published).
3. If the platform's answer to the *publish* call is lost, the post may or may not be live: mark it
   `uncertain` and NEVER retry it automatically - a human checks the account. Double posts are worse than
   a missing one.
4. Failures that provably happened before publication (`failed_before_publish`) may be retried.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

FINAL = {"published", "uncertain", "skipped"}
RETRYABLE = {"failed_before_publish"}


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.items, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)                    # atomic on Windows and POSIX

    def can_attempt(self, key: str) -> bool:
        e = self.items.get(key)
        return e is None or e.get("status") in RETRYABLE

    def mark(self, key: str, status: str, **fields) -> dict:
        e = self.items.setdefault(key, {})
        e.update(fields, status=status, updated_at=datetime.now(timezone.utc).isoformat())
        self._save()
        return e

    def publish(self, key: str, upload, finish) -> str:
        """upload() -> remote id (may raise: nothing live yet); finish(remote_id) -> result dict.
        Returns the final status."""
        if not self.can_attempt(key):
            return self.items[key]["status"]
        self.mark(key, "uploading")
        try:
            remote_id = upload()
        except Exception as ex:
            self.mark(key, "failed_before_publish", error=type(ex).__name__)
            return "failed_before_publish"
        self.mark(key, "publishing", remote_id=remote_id)
        try:
            result = finish(remote_id)
        except PlatformError as ex:                   # the platform answered "no": nothing went live
            self.mark(key, "failed", error=str(ex))
            return "failed"
        except Exception as ex:                       # the answer was lost: it may be live -> never retry
            self.mark(key, "uncertain", error=f"publish answer lost: {type(ex).__name__}")
            return "uncertain"
        self.mark(key, "published", **(result or {}))
        return "published"


class PlatformError(RuntimeError):
    """The platform explicitly rejected the request (an answer was received)."""
