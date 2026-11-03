"""Qt controller that runs the pure inspection service on a worker thread."""

from __future__ import annotations

import queue
import threading
from typing import Callable, Iterable, Optional

from PyQt6 import QtCore

from anylabeling.services.inspection.manifest import (
    build_manifest,
    changed_relative_paths,
    filter_manifest,
)
from anylabeling.services.inspection.models import (
    InspectionProfile,
    Manifest,
    RunReport,
    RunScope,
)
from anylabeling.services.inspection.profiles import (
    RuleCatalog,
    build_default_catalog,
)
from anylabeling.services.inspection.runner import InspectionRunner


class InspectionController(QtCore.QObject):
    """Owns one cancellable run and marshals messages back to the GUI."""

    progress = QtCore.pyqtSignal(int, int, str)
    stage_changed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object, object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        parent: Optional[QtCore.QObject] = None,
        catalog: Optional[RuleCatalog] = None,
    ) -> None:
        super().__init__(parent)
        self.catalog = catalog or build_default_catalog()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._messages: queue.Queue = queue.Queue()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.poll)
        self.last_report: Optional[RunReport] = None
        self.last_manifest: Optional[Manifest] = None

    def start(
        self,
        profile: InspectionProfile,
        scope: RunScope,
        *,
        dataset_root: str = "",
        output_dir: str = "",
        image_paths: Optional[Iterable[str]] = None,
        manifest: Optional[Manifest] = None,
        excluded_paths: Optional[Iterable[str]] = None,
        previous_manifest: Optional[Manifest] = None,
        allow_partial: bool = False,
        generation: int = 0,
    ) -> None:
        """Start one run; caller must not start while another is active."""
        if self.is_running():
            raise RuntimeError("inspection run already active")
        self._cancel.clear()
        self._messages = queue.Queue()
        self.last_report = None
        self.last_manifest = None
        paths = list(image_paths) if image_paths is not None else None
        excluded = list(excluded_paths) if excluded_paths else []

        def work() -> None:
            try:
                if manifest is None:
                    self._messages.put(("stage", "扫描文件"))
                    built = build_manifest(
                        dataset_root,
                        output_dir,
                        image_paths=paths,
                        excluded_paths=excluded,
                        should_cancel=self._cancel.is_set,
                    )
                else:
                    built = manifest
                if (
                    scope is RunScope.CHANGED_FILES
                    and previous_manifest is not None
                ):
                    changed = changed_relative_paths(previous_manifest, built)
                    built = filter_manifest(built, changed)
                    self._messages.put(
                        ("stage", f"已变更文件 {len(changed)} 个")
                    )
                if self._cancel.is_set():
                    self._messages.put(("stage", "正在取消"))
                else:
                    self._messages.put(("stage", "执行检查"))
                runner = InspectionRunner(
                    self.catalog,
                    allow_partial_profile=allow_partial,
                )
                report = runner.run(
                    built,
                    profile,
                    scope,
                    cancel_event=self._cancel,
                    progress=lambda index, total, path: self._messages.put(
                        ("progress", index, total, path)
                    ),
                    generation=generation,
                )
                self._messages.put(("finished", report, built))
            except Exception as error:  # noqa: BLE001
                self._messages.put(
                    ("failed", f"{type(error).__name__}: {error}")
                )

        self._thread = threading.Thread(
            target=work, name="inspection-run", daemon=True
        )
        self._thread.start()
        self._timer.start()

    def cancel(self) -> None:
        self._cancel.set()
        self.stage_changed.emit("正在取消")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll(self) -> None:
        """Drain worker messages without blocking the GUI thread."""
        for _ in range(200):
            try:
                message = self._messages.get_nowait()
            except queue.Empty:
                break
            kind = message[0]
            if kind == "progress":
                self.progress.emit(message[1], message[2], message[3])
            elif kind == "stage":
                self.stage_changed.emit(message[1])
            elif kind == "finished":
                self.last_report = message[1]
                self.last_manifest = message[2]
                self._thread = None
                self._timer.stop()
                self.finished.emit(message[1], message[2])
            elif kind == "failed":
                self._thread = None
                self._timer.stop()
                self.failed.emit(message[1])
        if self._thread is None:
            self._timer.stop()
