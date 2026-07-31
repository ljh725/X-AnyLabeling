"""Background worker for dataset filter index builds."""

import time
from typing import Callable, List, Optional

from PyQt6 import QtCore

from .index import (
    DatasetFilterIndex,
    make_staging_db_path,
    remove_database_files,
)

DEFAULT_PROGRESS_INTERVAL_SECONDS = 0.1


class DatasetIndexWorker(QtCore.QThread):
    """Build or refresh the dataset index in a background thread.

    SQLite connections must not be shared across threads, so the worker creates
    its own DatasetFilterIndex instance inside run().
    """

    progress_changed = QtCore.pyqtSignal(int, int, str)
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    cancelled = QtCore.pyqtSignal(object)

    def __init__(
        self,
        mode: str,
        db_path: str,
        image_files: List[str],
        output_dir: Optional[str] = None,
        dataset_root: Optional[str] = None,
        parent=None,
        *,
        progress_interval_seconds: float = DEFAULT_PROGRESS_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the dataset index worker.

        Args:
            mode: Operation mode, either "refresh" or "rebuild".
            db_path: SQLite cache database path.
            image_files: Image files in current dataset order.
            output_dir: Optional annotation output directory.
            dataset_root: Root directory used to identify this cache snapshot.
            parent: Optional Qt parent.
            progress_interval_seconds: Minimum time between non-terminal
                progress signals.
            clock: Monotonic clock used to enforce progress throttling.
        """
        super().__init__(parent)
        self.mode = mode
        self.db_path = db_path
        self.image_files = list(image_files)
        self.output_dir = output_dir
        self.dataset_root = dataset_root
        self._cancel_requested = False
        self._progress_interval_seconds = max(0.0, progress_interval_seconds)
        self._clock = clock
        self._last_progress_at: Optional[float] = None

    def cancel(self) -> None:
        """Request cancellation for the running index operation."""
        self._cancel_requested = True

    def _is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._cancel_requested

    def _emit_progress(self, current: int, total: int, filename: str) -> None:
        """Forward throttled index progress to the UI thread via Qt signal."""
        now = self._clock()
        is_terminal = total > 0 and current >= total
        if (
            self._last_progress_at is not None
            and not is_terminal
            and now - self._last_progress_at < self._progress_interval_seconds
        ):
            return
        self._last_progress_at = now
        self.progress_changed.emit(current, total, filename)

    def run(self) -> None:
        """Run the selected index operation in this worker thread."""
        staged_db_path = None
        if self.mode == "rebuild":
            staged_db_path = make_staging_db_path(self.db_path)
            index = DatasetFilterIndex(staged_db_path, journal_mode="delete")
        else:
            index = DatasetFilterIndex(self.db_path)
        try:
            if self.mode == "rebuild":
                result = index.rebuild(
                    self.image_files,
                    self.output_dir,
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                    dataset_root=self.dataset_root,
                )
            else:
                result = index.load_or_build(
                    self.image_files,
                    self.output_dir,
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                    dataset_root=self.dataset_root,
                )
            if result.fatal_error:
                raise RuntimeError("Dataset index update failed")
            if not result.cancelled and not index.integrity_check():
                raise RuntimeError("Dataset index integrity check failed")
            index.close()
            if result.cancelled:
                remove_database_files(staged_db_path)
                self.cancelled.emit(result)
            else:
                result.target_db_path = self.db_path
                result.staged_db_path = staged_db_path
                self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            index.close()
            remove_database_files(staged_db_path)
            self.failed.emit(str(exc))
