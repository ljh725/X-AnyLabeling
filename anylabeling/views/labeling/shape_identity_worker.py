"""Qt worker for non-blocking project-wide Shape identity assignment."""

from __future__ import annotations

from typing import Iterable

from PyQt6 import QtCore

from .shape_identity_project import (
    ProjectShapeIdentityResult,
    discover_project_json_files,
    ensure_project_shape_ids,
)


class ProjectShapeIdentityCancelled(Exception):
    """Internal signal used to stop a project identity scan."""


class ProjectShapeIdentityWorker(QtCore.QThread):
    """Run project JSON discovery and ID persistence off the UI thread."""

    progress = QtCore.pyqtSignal(int, int)
    completed = QtCore.pyqtSignal(object)
    cancelled = QtCore.pyqtSignal()

    def __init__(self, roots: Iterable[str]) -> None:
        """Create a worker that scans the supplied project roots."""
        super().__init__()
        self.roots = tuple(str(root) for root in roots if root)
        self._cancelled = False
        self._last_progress = 0

    def cancel(self) -> None:
        """Request cancellation after the current file operation."""
        self._cancelled = True

    def run(self) -> None:
        """Discover annotation files and persist their repaired identities."""
        paths = discover_project_json_files(self.roots)
        self.progress.emit(0, len(paths))
        try:
            result = ensure_project_shape_ids(
                paths,
                progress_callback=self._emit_progress,
            )
        except ProjectShapeIdentityCancelled:
            self.cancelled.emit()
            return
        self.completed.emit(result)

    def _emit_progress(self, current: int, total: int) -> None:
        """Forward progress unless cancellation was requested."""
        if self._cancelled:
            raise ProjectShapeIdentityCancelled
        step = max(total // 100, 1)
        if current != total and current - self._last_progress < step:
            return
        self._last_progress = current
        self.progress.emit(current, total)
