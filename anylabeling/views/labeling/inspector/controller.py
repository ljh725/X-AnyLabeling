"""Qt controller that runs the pure inspection service on a worker thread."""

from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from PyQt6 import QtCore

from anylabeling.services.inspection.manifest import (
    build_manifest,
    compare_manifests,
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
    effective_profile_snapshot,
)
from anylabeling.services.inspection.runner import InspectionRunner


@dataclass(frozen=True)
class RunContext:
    """Immutable identity of one background run's inputs."""

    token: str
    generation: int
    dataset_root: str
    output_dir: str
    profile_id: str
    profile_fingerprint: str
    config_digest: str
    scope: str

    def to_dict(self) -> dict[str, object]:
        return {
            "token": self.token,
            "generation": self.generation,
            "dataset_root": self.dataset_root,
            "output_dir": self.output_dir,
            "profile_id": self.profile_id,
            "profile_fingerprint": self.profile_fingerprint,
            "config_digest": self.config_digest,
            "scope": self.scope,
        }


class InspectionController(QtCore.QObject):
    """Owns one cancellable run and marshals messages back to the GUI."""

    progress = QtCore.pyqtSignal(str, int, int, str)
    scan_progress = QtCore.pyqtSignal(str, int, int, str)
    stage_changed = QtCore.pyqtSignal(str, str)
    finished = QtCore.pyqtSignal(object, object, str)
    failed = QtCore.pyqtSignal(str, str)

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
        self.active_context: Optional[RunContext] = None

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
        previous_report: Optional[RunReport] = None,
        allow_partial: bool = False,
        generation: int = 0,
        scope_notes: Optional[Iterable[str]] = None,
    ) -> None:
        """Start one run; caller must not start while another is active."""
        if self.is_running():
            raise RuntimeError("inspection run already active")
        context = self._build_context(
            profile,
            scope,
            dataset_root=dataset_root,
            output_dir=output_dir,
            generation=generation,
        )
        self._cancel.clear()
        messages: queue.Queue = queue.Queue()
        self._messages = messages
        self.last_report = None
        self.last_manifest = None
        self.active_context = context
        paths = list(image_paths) if image_paths is not None else None
        excluded = list(excluded_paths) if excluded_paths else []
        notes = [str(note) for note in scope_notes or () if str(note).strip()]

        def emit(kind: str, *payload) -> None:
            messages.put((context.token, kind, *payload))

        def work() -> None:
            try:
                if manifest is None:
                    emit("stage", "扫描文件")
                    built = build_manifest(
                        dataset_root,
                        output_dir,
                        image_paths=paths,
                        excluded_paths=excluded,
                        should_cancel=self._cancel.is_set,
                        progress=lambda index, total, path: emit(
                            "scan_progress", index, total, path
                        ),
                    )
                else:
                    built = manifest
                if scope is RunScope.CHANGED_FILES:
                    config_changed = self._config_changed(
                        previous_report, profile
                    )
                    delta = compare_manifests(
                        previous_manifest,
                        built,
                        config_changed=config_changed,
                    )
                    notes.extend(delta.notes())
                    if config_changed:
                        notes.append(
                            "方案或规则实现版本变化，已保守检查全部文件"
                        )
                    if delta.changed:
                        built = filter_manifest(built, delta.changed)
                    else:
                        notes.append(
                            "未发现已变更文件：本次未执行任何规则，"
                            "不能视为检查通过"
                        )
                    if delta.removed:
                        notes.append(
                            "已移除文件不在本次请求范围内，仅保留为范围记录"
                        )
                    emit(
                        "stage",
                        "已变更文件 {} 个".format(len(delta.changed)),
                    )
                if self._cancel.is_set():
                    emit("stage", "正在取消")
                else:
                    emit("stage", "执行检查")
                runner = InspectionRunner(
                    self.catalog,
                    allow_partial_profile=allow_partial,
                )
                report = runner.run(
                    built,
                    profile,
                    scope,
                    cancel_event=self._cancel,
                    progress=lambda index, total, path: emit(
                        "progress", index, total, path
                    ),
                    generation=generation,
                    scope_notes=notes,
                )
                emit("finished", report, built)
            except Exception as error:  # noqa: BLE001
                emit("failed", f"{type(error).__name__}: {error}")

        self._thread = threading.Thread(
            target=work, name="inspection-run", daemon=True
        )
        self._thread.start()
        self._timer.start()

    def _build_context(
        self,
        profile: InspectionProfile,
        scope: RunScope,
        *,
        dataset_root: str,
        output_dir: str,
        generation: int,
    ) -> RunContext:
        snapshot = effective_profile_snapshot(profile, self.catalog)
        return RunContext(
            token=uuid.uuid4().hex,
            generation=int(generation),
            dataset_root=str(dataset_root or ""),
            output_dir=str(output_dir or ""),
            profile_id=profile.profile_id,
            profile_fingerprint=profile.fingerprint(),
            config_digest=str(snapshot.get("snapshot_digest", "")),
            scope=scope.value,
        )

    def _config_changed(
        self,
        previous_report: Optional[RunReport],
        profile: InspectionProfile,
    ) -> bool:
        if previous_report is None:
            return False
        snapshot = effective_profile_snapshot(profile, self.catalog)
        current_digest = str(snapshot.get("snapshot_digest", ""))
        previous_digest = previous_report.config_digest
        if previous_digest and current_digest:
            return previous_digest != current_digest
        previous_profile = previous_report.profile_snapshot.get("profile", {})
        previous_fingerprint = previous_report.profile_snapshot.get(
            "profile_fingerprint", ""
        )
        if isinstance(previous_profile, dict):
            previous_id = str(previous_profile.get("profile_id", ""))
            if previous_id and previous_id != profile.profile_id:
                return True
        return bool(
            previous_fingerprint
            and previous_fingerprint != profile.fingerprint()
        )

    def cancel(self) -> None:
        self._cancel.set()
        token = self.active_context.token if self.active_context else ""
        if token:
            self.stage_changed.emit(token, "正在取消")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll(self) -> None:
        """Drain worker messages without blocking the GUI thread."""
        active_token = self.active_context.token if self.active_context else ""
        for _ in range(200):
            try:
                message = self._messages.get_nowait()
            except queue.Empty:
                break
            token = str(message[0])
            if active_token and token != active_token:
                # A previous run's late message must not touch this run.
                continue
            kind = message[1]
            if kind == "progress":
                self.progress.emit(token, message[2], message[3], message[4])
            elif kind == "scan_progress":
                self.scan_progress.emit(
                    token, message[2], message[3], message[4]
                )
            elif kind == "stage":
                self.stage_changed.emit(token, message[2])
            elif kind == "finished":
                self.last_report = message[2]
                self.last_manifest = message[3]
                self._thread = None
                self._timer.stop()
                self.finished.emit(message[2], message[3], token)
            elif kind == "failed":
                self._thread = None
                self._timer.stop()
                self.failed.emit(token, message[2])
        if self._thread is None:
            self._timer.stop()
