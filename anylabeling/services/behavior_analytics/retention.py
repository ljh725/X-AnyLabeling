"""Explicit and retention-based cleanup for local behavior logs."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class CleanupSummary:
    """Result of one cleanup operation."""

    files_scanned: int
    files_changed: int
    events_removed: int
    bytes_removed: int


def cleanup_event_logs(
    root_dir: str | Path,
    *,
    retention_days: int | None = None,
    project_ids: set[str] | frozenset[str] | None = None,
    start_utc: str | None = None,
    end_utc: str | None = None,
) -> CleanupSummary:
    """Remove only matching local event records using atomic file replacement.

    Annotation JSON files and images are outside ``root_dir`` and are never
    touched. Corrupt or unknown-schema lines are retained unless they can be
    identified by an explicit project/time scope.
    """
    if retention_days is not None and retention_days < 0:
        raise ValueError("retention_days must be non-negative")
    if not any(
        value is not None
        for value in (retention_days, project_ids, start_utc, end_utc)
    ):
        raise ValueError("at least one cleanup scope is required")
    root = Path(root_dir)
    cutoff = None
    if retention_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    project_ids = set(project_ids or ())
    summary = CleanupSummary(0, 0, 0, 0)
    for path in sorted((root / "events").glob("*.jsonl")):
        summary = CleanupSummary(
            summary.files_scanned + 1,
            summary.files_changed,
            summary.events_removed,
            summary.bytes_removed,
        )
        original = path.read_bytes()
        kept: list[bytes] = []
        removed = 0
        for raw_line in original.splitlines(keepends=True):
            if _line_matches(
                raw_line,
                cutoff=cutoff,
                project_ids=project_ids,
                start_utc=start_utc,
                end_utc=end_utc,
            ):
                removed += 1
            else:
                kept.append(raw_line)
        updated = b"".join(kept)
        if updated == original:
            continue
        _atomic_replace(path, updated)
        summary = CleanupSummary(
            summary.files_scanned,
            summary.files_changed + 1,
            summary.events_removed + removed,
            summary.bytes_removed + len(original) - len(updated),
        )
    return summary


def _line_matches(
    raw_line: bytes,
    *,
    cutoff: datetime | None,
    project_ids: set[str],
    start_utc: str | None,
    end_utc: str | None,
) -> bool:
    """Return whether a JSONL line is inside the requested cleanup scope."""
    try:
        data = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    if project_ids and data.get("project_id") not in project_ids:
        return False
    occurred_at = str(data.get("occurred_at_utc", ""))
    if start_utc and occurred_at < start_utc:
        return False
    if end_utc and occurred_at > end_utc:
        return False
    if cutoff is not None:
        try:
            occurred = datetime.fromisoformat(
                occurred_at.replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if occurred >= cutoff:
            return False
    return True


def _atomic_replace(path: Path, content: bytes) -> None:
    """Replace one shard without exposing a partially written file."""
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
