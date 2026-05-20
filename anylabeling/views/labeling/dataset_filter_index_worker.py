"""Background worker for dataset filter index builds."""

from typing import List, Optional

from PyQt6 import QtCore

from .dataset_filter_index import DatasetFilterIndex


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
        parent=None,
    ):
        """Initialize the dataset index worker.

        Args:
            mode: Operation mode, either "refresh" or "rebuild".
            db_path: SQLite cache database path.
            image_files: Image files in current dataset order.
            output_dir: Optional annotation output directory.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.mode = mode
        self.db_path = db_path
        self.image_files = list(image_files)
        self.output_dir = output_dir
        self._cancel_requested = False

    def cancel(self) -> None:
        """Request cancellation for the running index operation."""
        self._cancel_requested = True

    def _is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._cancel_requested

    def _emit_progress(self, current: int, total: int, filename: str) -> None:
        """Forward index progress to the UI thread via Qt signal."""
        self.progress_changed.emit(current, total, filename)

    def run(self) -> None:
        """Run the selected index operation in this worker thread."""
        index = DatasetFilterIndex(self.db_path)
        try:
            if self.mode == "rebuild":
                result = index.rebuild(
                    self.image_files,
                    self.output_dir,
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                )
            else:
                result = index.load_or_build(
                    self.image_files,
                    self.output_dir,
                    progress_callback=self._emit_progress,
                    cancel_check=self._is_cancelled,
                )
            index.close()
            if result.cancelled:
                self.cancelled.emit(result)
            else:
                self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            index.close()
            self.failed.emit(str(exc))
