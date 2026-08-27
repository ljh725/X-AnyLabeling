"""Qt-independent cancellable export job used by the UI worker adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from .analysis import AnalysisFilter, ReadQuality
from .bundle import export_analysis_bundle
from .pipeline import iter_event_stream
from .schema import EventEnvelope


@dataclass(frozen=True)
class ExportProgress:
    """Bounded progress snapshot emitted at shard or batch boundaries."""

    phase: str
    processed_events: int
    accepted_events: int
    current_source: str | None = None


class ExportCancellation:
    """Thread-safe cancellation token shared by the UI and export job."""

    def __init__(self) -> None:
        """Create a clear cancellation token."""
        self._event = Event()

    def cancel(self) -> None:
        """Request cancellation."""
        self._event.set()

    def is_cancelled(self) -> bool:
        """Return whether cancellation was requested."""
        return self._event.is_set()


class ExportCancelledError(RuntimeError):
    """Raised when an export stops at a configured checkpoint."""


def run_export_job(  # noqa: C901
    output_dir: str | Path,
    sources: Iterable[str | Path],
    *,
    event_filter: AnalysisFilter | None = None,
    comparison_sources: Iterable[str | Path] | None = None,
    comparison_filter: AnalysisFilter | None = None,
    cancellation: ExportCancellation | None = None,
    on_progress: Callable[[ExportProgress], None] | None = None,
    batch_size: int = 256,
) -> Path:
    """Run a local export and publish only after the bundle is complete."""
    token = cancellation or ExportCancellation()
    quality = ReadQuality()
    processed = 0
    accepted = 0

    def progress(batch_count: int) -> None:
        """Publish a bounded batch progress snapshot."""
        nonlocal processed
        processed += batch_count
        if on_progress:
            on_progress(ExportProgress("read", processed, accepted))
        if token.is_cancelled():
            raise ExportCancelledError("behavior analytics export cancelled")

    def filtered_events() -> Iterable[EventEnvelope]:
        """Yield primary events while applying filters and cancellation."""
        nonlocal accepted
        for event in iter_event_stream(
            sources,
            quality=quality,
            batch_size=batch_size,
            on_batch=progress,
        ):
            if token.is_cancelled():
                raise ExportCancelledError(
                    "behavior analytics export cancelled"
                )
            if event_filter and not event_filter.matches(event):
                continue
            accepted += 1
            yield event

    def filtered_comparison_events() -> Iterable[EventEnvelope]:
        """Yield comparison events only when a second range is requested."""
        if comparison_sources is None:
            return
        comparison_quality = ReadQuality()
        for event in iter_event_stream(
            comparison_sources,
            quality=comparison_quality,
            batch_size=batch_size,
            on_batch=progress,
        ):
            if token.is_cancelled():
                raise ExportCancelledError(
                    "behavior analytics export cancelled"
                )
            if comparison_filter is None or comparison_filter.matches(event):
                yield event

    try:
        if token.is_cancelled():
            raise ExportCancelledError("behavior analytics export cancelled")
        if on_progress:
            on_progress(ExportProgress("publish", processed, accepted))
        return export_analysis_bundle(
            output_dir,
            filtered_events(),
            quality=quality,
            event_filter=event_filter,
            comparison_events=(
                filtered_comparison_events()
                if comparison_sources is not None
                else None
            ),
            cancel_check=token.is_cancelled,
        )
    except ExportCancelledError:
        raise
    except RuntimeError as exc:
        if token.is_cancelled():
            raise ExportCancelledError(str(exc)) from exc
        raise
