"""Non-blocking local JSONL event recorder."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .catalog import sanitize_event, validate_payload
from .retention import CleanupSummary, cleanup_event_logs
from .schema import EventEnvelope
from .versions import EVENT_ENVELOPE_VERSION, RECORDING_STORAGE_VERSION


@dataclass(frozen=True)
class RecorderHealth:
    """Operational counters that are safe to show in a diagnostics view."""

    accepted: int
    written: int
    dropped: int
    invalid: int
    write_errors: int
    privacy_fields_removed: int
    last_error: str | None
    sequence_gaps: int = 0
    flush_timeouts: int = 0
    current_shard: str | None = None


class LocalEventRecorder:
    """Append validated events to local UTC-hour JSONL shards.

    The public ``emit`` method never waits for disk I/O. Events are assigned a
    per-application-session sequence number before entering the bounded queue;
    rejected events therefore leave a diagnosable sequence gap.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        enabled: bool = False,
        queue_max_events: int = 2048,
        max_event_bytes: int = 16_384,
        batch_size: int = 64,
        flush_interval_ms: int = 500,
        start_worker: bool = True,
    ) -> None:
        """Initialize a local recorder with an optional worker thread."""
        if queue_max_events <= 0:
            raise ValueError("queue_max_events must be positive")
        if max_event_bytes <= 0:
            raise ValueError("max_event_bytes must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if flush_interval_ms <= 0:
            raise ValueError("flush_interval_ms must be positive")
        self.root_dir = Path(root_dir)
        self.enabled = enabled
        self.max_event_bytes = max_event_bytes
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self._queue: queue.Queue[EventEnvelope | None] | None = None
        self._worker: threading.Thread | None = None
        self._closed = False
        self._condition = threading.Condition()
        self._accepted = 0
        self._written = 0
        self._dropped = 0
        self._invalid = 0
        self._write_errors = 0
        self._privacy_fields_removed = 0
        self._sequence_gaps = 0
        self._flush_timeouts = 0
        self._last_error: str | None = None
        self._next_sequence: dict[str, int] = {}
        self._gap_sequences: dict[str, list[int]] = {}
        self._shard_stats: dict[Path, dict[str, Any]] = {}
        self._streams: dict[Path, Any] = {}
        self._active_shard: Path | None = None
        if enabled:
            self._queue = queue.Queue(maxsize=queue_max_events)
            if start_worker:
                self._worker = threading.Thread(
                    target=self._run,
                    name="xanylabeling-behavior-recorder",
                    daemon=True,
                )
                self._worker.start()

    @property
    def health(self) -> RecorderHealth:
        """Return a snapshot of recorder health counters."""
        with self._condition:
            return RecorderHealth(
                accepted=self._accepted,
                written=self._written,
                dropped=self._dropped,
                invalid=self._invalid,
                write_errors=self._write_errors,
                privacy_fields_removed=self._privacy_fields_removed,
                last_error=self._last_error,
                sequence_gaps=self._sequence_gaps,
                flush_timeouts=self._flush_timeouts,
                current_shard=(
                    self._active_shard.name if self._active_shard else None
                ),
            )

    @staticmethod
    def cleanup(
        root_dir: str | Path,
        *,
        retention_days: int | None = None,
        project_ids: set[str] | frozenset[str] | None = None,
        start_utc: str | None = None,
        end_utc: str | None = None,
    ) -> CleanupSummary:
        """Clean local event shards without touching annotation assets."""
        return cleanup_event_logs(
            root_dir,
            retention_days=retention_days,
            project_ids=project_ids,
            start_utc=start_utc,
            end_utc=end_utc,
        )

    def emit(self, event: EventEnvelope) -> bool:
        """Validate, sanitize and enqueue an event without blocking.

        Returns:
            ``True`` when the event was accepted by the bounded queue; ``False``
            when recording is disabled, invalid, too large or the queue is full.
        """
        if not self.enabled or self._closed or self._queue is None:
            return False
        sequence_no = self._allocate_sequence(event.app_session_id)
        try:
            sanitized, removed = sanitize_event(event)
            validate_payload(event.event_type, sanitized.payload)
            sanitized = self._upgrade_legacy_event(sanitized, sequence_no)
            encoded = self._encode(sanitized)
            encoded = self._encode(sanitized)
        except (TypeError, ValueError, OverflowError) as exc:
            with self._condition:
                self._invalid += 1
                self._last_error = str(exc)
                self._record_gap_locked(event.app_session_id, sequence_no)
            return False
        if len(encoded) > self.max_event_bytes:
            with self._condition:
                self._invalid += 1
                self._last_error = "event exceeds max_event_bytes"
                self._record_gap_locked(event.app_session_id, sequence_no)
            return False
        try:
            self._queue.put_nowait(sanitized)
        except queue.Full:
            with self._condition:
                self._dropped += 1
                self._record_gap_locked(event.app_session_id, sequence_no)
            return False
        with self._condition:
            self._accepted += 1
            self._privacy_fields_removed += removed
        return True

    def flush(self, timeout: float = 1.0) -> bool:
        """Wait briefly for accepted events to reach disk."""
        if self._queue is None or self._worker is None:
            return self._queue is None or self._queue.unfinished_tasks == 0
        deadline = time.monotonic() + max(0.0, timeout)
        while self._queue.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._condition:
                    self._flush_timeouts += 1
                return False
            time.sleep(min(0.01, remaining))
        return True

    def close(self, timeout: float = 1.0) -> bool:
        """Stop the worker after a bounded final flush."""
        if self._closed:
            return True
        flushed = self.flush(timeout)
        self._closed = True
        if self._queue is not None and self._worker is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                flushed = False
            self._worker.join(timeout=max(0.0, timeout))
            flushed = flushed and not self._worker.is_alive()
        return flushed

    @staticmethod
    def _upgrade_legacy_event(
        event: EventEnvelope, sequence_no: int
    ) -> EventEnvelope:
        """Adapt legacy action spans while preserving explicit old inputs."""
        target_schema = (
            event.schema_version
            if event.schema_version < EVENT_ENVELOPE_VERSION
            else EVENT_ENVELOPE_VERSION
        )
        if event.event_type != "action_span":
            return replace(
                event,
                schema_version=target_schema,
                sequence_no=sequence_no,
            )
        payload = event.payload or {}
        result = (
            "interrupted" if event.result == "incomplete" else event.result
        )
        end = event.ended_monotonic_ms or event.monotonic_ms
        start = event.started_monotonic_ms
        if start is None:
            start = max(0, end - (event.duration_ms or 0))
        phase = event.action_phase
        if phase in (None, "started"):
            phase = {
                "success": "committed",
                "cancelled": "cancelled",
                "no_change": "no_change",
                "interrupted": "interrupted",
            }.get(result, "interrupted")
        return replace(
            event,
            schema_version=target_schema,
            sequence_no=sequence_no,
            result=result,
            action_id=event.action_id or f"legacy-{event.event_id}",
            action_phase=phase,
            action_type=event.action_type
            or str(payload.get("action", "action_span")),
            started_monotonic_ms=start,
            ended_monotonic_ms=end,
            interruption_reason=(
                event.interruption_reason
                or ("legacy_incomplete" if result == "interrupted" else None)
            ),
        )

    def _allocate_sequence(self, app_session_id: str) -> int:
        """Allocate a sequence number before validation or queue admission."""
        with self._condition:
            sequence_no = self._next_sequence.get(app_session_id, 0) + 1
            self._next_sequence[app_session_id] = sequence_no
            return sequence_no

    def _record_gap_locked(
        self, app_session_id: str, sequence_no: int
    ) -> None:
        """Record an event rejected before durable storage."""
        self._sequence_gaps += 1
        self._gap_sequences.setdefault(app_session_id, []).append(sequence_no)

    @staticmethod
    def _encode(event: EventEnvelope) -> bytes:
        """Encode one event deterministically for size checks and writing."""
        return (
            json.dumps(
                event.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

    @staticmethod
    def _shard_path(root_dir: Path, event: EventEnvelope) -> Path:
        """Return the UTC-hour path for an event."""
        hour = event.occurred_at_utc[:13].replace("T", "-")
        return root_dir / "events" / f"events-{hour}.jsonl"

    def _run(self) -> None:
        """Consume the queue in bounded batches until the sentinel."""
        assert self._queue is not None
        while True:
            try:
                first = self._queue.get(timeout=self.flush_interval_ms / 1000)
            except queue.Empty:
                continue
            if first is None:
                self._queue.task_done()
                self._finalize_all_shards()
                return
            batch = [first]
            stop_after_batch = False
            while len(batch) < self.batch_size:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    self._queue.task_done()
                    stop_after_batch = True
                    break
                batch.append(item)
            self._write_batch(batch)
            for _ in batch:
                self._queue.task_done()
            if stop_after_batch:
                self._finalize_all_shards()
                return

    def _write_batch(self, events: list[EventEnvelope]) -> None:
        """Write one bounded batch grouped by UTC-hour shard."""
        groups: dict[Path, list[EventEnvelope]] = {}
        for event in events:
            groups.setdefault(
                self._shard_path(self.root_dir, event), []
            ).append(event)
        for path in sorted(groups):
            self._write_group(path, groups[path])

    def _write_group(self, path: Path, events: list[EventEnvelope]) -> None:
        """Append a same-shard event group and update its manifest state."""
        self._rotate_streams(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = self._streams.get(path)
            if stream is None:
                stream = path.open("ab")
                self._streams[path] = stream
            for event in events:
                stream.write(self._encode(event))
            stream.flush()
        except (OSError, TypeError, ValueError) as exc:
            stream = self._streams.pop(path, None)
            if stream is not None:
                stream.close()
            with self._condition:
                self._write_errors += len(events)
                self._last_error = str(exc)
                for event in events:
                    self._record_gap_locked(
                        event.app_session_id, event.sequence_no or 0
                    )
            return
        self._active_shard = path
        stats = self._shard_stats.setdefault(path, self._new_stats(path))
        for event in events:
            self._update_stats(stats, event)
        with self._condition:
            self._written += len(events)
        self._write_manifest(path, complete=False)

    def _rotate_streams(self, keep: Path) -> None:
        """Close older-hour handles before writing the current shard."""
        for path, stream in list(self._streams.items()):
            if path == keep:
                continue
            try:
                stream.flush()
            finally:
                stream.close()
            self._streams.pop(path, None)
            self._write_manifest(path, complete=True)

    @staticmethod
    def _new_stats(path: Path) -> dict[str, Any]:
        """Create in-memory statistics for one shard."""
        return {
            "path": path,
            "event_count": 0,
            "first_utc": None,
            "last_utc": None,
            "sessions": {},
            "schema_versions": {},
            "dropped_count": 0,
            "error_count": 0,
        }

    @staticmethod
    def _update_stats(stats: dict[str, Any], event: EventEnvelope) -> None:
        """Add one event to a shard manifest accumulator."""
        stats["event_count"] += 1
        occurred = event.occurred_at_utc
        stats["first_utc"] = min(
            value for value in (stats["first_utc"], occurred) if value
        )
        stats["last_utc"] = max(
            value for value in (stats["last_utc"], occurred) if value
        )
        schema_key = str(event.schema_version)
        versions = stats["schema_versions"]
        versions[schema_key] = versions.get(schema_key, 0) + 1
        session = stats["sessions"].setdefault(
            event.app_session_id,
            {
                "first_sequence_no": event.sequence_no,
                "last_sequence_no": event.sequence_no,
            },
        )
        if event.sequence_no is not None:
            session["first_sequence_no"] = min(
                session["first_sequence_no"] or event.sequence_no,
                event.sequence_no,
            )
            session["last_sequence_no"] = max(
                session["last_sequence_no"] or event.sequence_no,
                event.sequence_no,
            )

    def _write_manifest(self, path: Path, *, complete: bool) -> None:
        """Write a manifest atomically without replacing the JSONL source."""
        stats = self._shard_stats.get(path)
        if stats is None or not path.exists():
            return
        manifest = {
            "storage_version": RECORDING_STORAGE_VERSION,
            "manifest_complete": complete,
            "file_name": path.name,
            "event_count": stats["event_count"],
            "first_utc": stats["first_utc"],
            "last_utc": stats["last_utc"],
            "session_sequence_ranges": stats["sessions"],
            "schema_versions": stats["schema_versions"],
            "dropped_count": stats["dropped_count"],
            "error_count": stats["error_count"],
            "sequence_gap_count": self._sequence_gaps,
            "sequence_gap_sequences": {
                key: list(value) for key, value in self._gap_sequences.items()
            },
            "write_error_count": self._write_errors,
            "file_size_bytes": path.stat().st_size,
            "sha256": (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if complete
                else None
            ),
        }
        manifest_path = path.with_name(f"{path.stem}.manifest.json")
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            dir=manifest_path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, manifest_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _finalize_all_shards(self) -> None:
        """Close all active streams and publish complete manifests."""
        for path, stream in list(self._streams.items()):
            try:
                stream.flush()
            finally:
                stream.close()
            self._streams.pop(path, None)
            self._write_manifest(path, complete=True)
        self._active_shard = None
