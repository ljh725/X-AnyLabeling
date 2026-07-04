"""
Background scan worker for the L1/L2 quality checker.

Runs ``run_quality_check`` off the UI thread so the Inspector stays
responsive during a single-file re-scan or a small-directory scan.  The
CLI and this worker share the same ``quality/`` core (acceptance
constraint: CLI flow and UI scan flow share one set of logic).

Usage in the panel::

    self._quality_thread = QualityScanThread(
        json_paths=[file_path],
        profile=self._quality_profile,
        input_root=input_root,
    )
    self._quality_thread.scan_finished.connect(self._on_quality_scan_done)
    self._quality_thread.error.connect(...)
    self._quality_thread.start()
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PyQt6 import QtCore

from .quality.quality_issue import QualityReport
from .quality.report_writer import run_quality_check
from .quality.threshold_profile import ThresholdProfile

logger = logging.getLogger(__name__)


class QualityScanThread(QtCore.QThread):
    """Background L1/L2 quality scan (reuses the CLI core)."""

    progress = QtCore.pyqtSignal(int, int, str)  # current, total, filename
    status_changed = QtCore.pyqtSignal(str)
    scan_finished = QtCore.pyqtSignal(object)  # QualityReport
    error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        json_paths: List[str],
        profile: ThresholdProfile,
        input_root: str = "",
        image_dir: Optional[str] = None,
        parent: Optional[QtCore.QObject] = None,
    ):
        """Initialize the worker.

        Args:
            json_paths: annotation JSON files to check.
            profile: pre-loaded threshold profile (shared with the CLI).
            input_root: descriptive source root.
            image_dir: optional image directory (recorded in source).
            parent: optional QObject parent.
        """
        super().__init__(parent)
        self._json_paths = list(json_paths)
        self._profile = profile
        self._input_root = input_root
        self._image_dir = image_dir
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation (best-effort; checked between files)."""
        self._cancelled = True

    def run(self) -> None:  # noqa: D401 — QThread override
        """Run the quality check and emit the resulting report."""
        try:
            total = len(self._json_paths)
            self.status_changed.emit(
                self.tr("正在执行 L1/L2 质检 ({0} 文件)...").format(total)
            )

            def on_progress(current, _total, filename):
                if self._cancelled:
                    return
                self.progress.emit(current, max(total, 1), filename)

            report: QualityReport = run_quality_check(
                json_paths=self._json_paths,
                profile=self._profile,
                input_root=self._input_root,
                image_dir=self._image_dir,
                progress_callback=on_progress,
            )
            if not self._cancelled:
                self.scan_finished.emit(report)
        except Exception as exc:  # noqa: BLE001 — isolate worker crashes
            logger.exception("Quality scan worker failed")
            self.error.emit(str(exc))
