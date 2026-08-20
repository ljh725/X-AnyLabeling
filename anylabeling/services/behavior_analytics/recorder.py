"""Non-blocking local JSONL event recorder."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from .catalog import sanitize_payload, validate_payload
from .schema import EventEnvelope


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


class LocalEventRecorder:
    """Append validated events to local monthly JSONL shards.

    The public ``emit`` method never waits for disk I/O. When recording is
    disabled, the queue is not created and no directory is touched.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        enabled: bool = False,
        queue_max_events: int = 2048,
        max_event_bytes: int = 16_384,
        start_worker: bool = True,
    ) -> None:
        """Initialize a local recorder with an optional worker thread."""
        if queue_max_events <= 0:
            raise ValueError("queue_max_events must be positive")
        if max_event_bytes <= 0:
            raise ValueError("max_event_bytes must be positive")
        self.root_dir = Path(root_dir)
        self.enabled = enabled
        self.max_event_bytes = max_event_bytes
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
        self._last_error: str | None = None
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
            )

    def emit(self, event: EventEnvelope) -> bool:
        """Validate, sanitize and enqueue an event without blocking.

        Returns:
            ``True`` when the event was accepted by the bounded queue; ``False``
            when recording is disabled, invalid, too large or the queue is full.
        """
        if not self.enabled or self._closed or self._queue is None:
            return False
        try:
            payload, removed = sanitize_payload(
                event.event_type, event.payload
            )
            validate_payload(event.event_type, payload)
            sanitized = replace(event, payload=payload or None)
            encoded = self._encode(sanitized)
        except (TypeError, ValueError, OverflowError) as exc:
            with self._condition:
                self._invalid += 1
                self._last_error = str(exc)
            return False
        if len(encoded) > self.max_event_bytes:
            with self._condition:
                self._invalid += 1
                self._last_error = "event exceeds max_event_bytes"
            return False
        try:
            self._queue.put_nowait(sanitized)
        except queue.Full:
            with self._condition:
                self._dropped += 1
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

    def _encode(self, event: EventEnvelope) -> bytes:
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

    def _run(self) -> None:
        """Consume the queue until the sentinel is received."""
        assert self._queue is not None
        while True:
            event = self._queue.get()
            try:
                if event is None:
                    return
                self._write_event(event)
            finally:
                self._queue.task_done()

    def _write_event(self, event: EventEnvelope) -> None:
        """Append one event to its UTC month shard."""
        month = event.occurred_at_utc[:7]
        path = self.root_dir / "events" / f"events-{month}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as stream:
                stream.write(self._encode(event))
        except (OSError, TypeError, ValueError) as exc:
            with self._condition:
                self._write_errors += 1
                self._last_error = str(exc)
            return
        with self._condition:
            self._written += 1
