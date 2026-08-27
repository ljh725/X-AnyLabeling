"""Qt worker adapter for cancellable local behavior analytics export."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore

from anylabeling.services.behavior_analytics import (
    AnalysisFilter,
    ExportCancellation,
    ExportCancelledError,
    ExportProgress,
    run_export_job,
)


class BehaviorAnalyticsExportWorker(QtCore.QThread):
    """Run deterministic export away from the labeling UI thread."""

    progress_changed = QtCore.pyqtSignal(str, int, int)
    export_succeeded = QtCore.pyqtSignal(str)
    export_failed = QtCore.pyqtSignal(str)
    export_cancelled = QtCore.pyqtSignal()

    def __init__(
        self,
        output_dir: str | Path,
        sources: list[str | Path],
        *,
        event_filter: AnalysisFilter,
        comparison_sources: list[str | Path] | None = None,
        comparison_filter: AnalysisFilter | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        """Initialize one single-use worker and its cancellation token."""
        super().__init__(parent)
        self._output_dir = output_dir
        self._sources = sources
        self._event_filter = event_filter
        self._comparison_sources = comparison_sources
        self._comparison_filter = comparison_filter
        self._cancellation = ExportCancellation()

    def cancel(self) -> None:
        """Request cancellation at the next read or publish checkpoint."""
        self._cancellation.cancel()

    def run(self) -> None:
        """Execute the local export and emit only small UI-safe snapshots."""
        try:
            bundle = run_export_job(
                self._output_dir,
                self._sources,
                event_filter=self._event_filter,
                comparison_sources=self._comparison_sources,
                comparison_filter=self._comparison_filter,
                cancellation=self._cancellation,
                on_progress=self._on_progress,
            )
        except ExportCancelledError:
            self.export_cancelled.emit()
        except (FileExistsError, OSError, ValueError) as exc:
            self.export_failed.emit(str(exc))
        else:
            self.export_succeeded.emit(str(bundle))

    def _on_progress(self, snapshot: ExportProgress) -> None:
        """Forward bounded progress from the worker thread."""
        self.progress_changed.emit(
            snapshot.phase,
            snapshot.processed_events,
            snapshot.accepted_events,
        )
