"""Qt worker that owns the SQLite connection of a queue build scan.

The worker wraps the pure-Python :func:`scan_dataset` in a ``QThread``:
progress and cancellation cross thread boundaries as signals, and the
staging database connection is created and closed inside ``run`` so no
database handle ever leaks into the GUI thread.
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore

from ...virtual_review import QueueBuildRequest, QueueDraft


class DatasetQueueBuildWorker(QtCore.QThread):
    """Run one cancellable dataset scan on its own thread."""

    progress_reported = QtCore.pyqtSignal(int, int, str)
    draft_ready = QtCore.pyqtSignal(object)
    scan_failed = QtCore.pyqtSignal(str)

    def __init__(
        self, request: QueueBuildRequest, parent: Optional[QtCore.QObject]
    ) -> None:
        """Prepare the worker for one build request."""

        super().__init__(parent)
        self._request = request
        self._cancel_requested = False

    def request_cancel(self) -> None:
        """Ask the running scan to stop at the next file boundary."""

        self._cancel_requested = True

    def run(self) -> None:  # noqa: D102 - QThread override
        from ...virtual_review import scan_dataset

        try:
            draft = scan_dataset(
                self._request,
                progress=self.progress_reported.emit,
                cancel=lambda: self._cancel_requested,
            )
        except Exception as exc:  # noqa: BLE001 - reported via signal
            self.scan_failed.emit(str(exc))
            return
        self.draft_ready.emit(draft)


__all__ = [
    "DatasetQueueBuildWorker",
    "QueueBuildRequest",
    "QueueDraft",
]
