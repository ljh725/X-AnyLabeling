"""History integration kept separate from the thumbnail grid implementation."""

import copy
import json
import os.path as osp
import sqlite3
from dataclasses import asdict

from PyQt6 import QtCore, QtWidgets

from .history_panel import HistoryPanel
from .history_store import document_digest, read_document, write_journal
from .page_diff import identity
from .preview import ThumbnailPreview
from ...dataset_index.thumbnail_query import ThumbnailQuery


class HistoryBrowser:
    """Connect durable operations to explicit navigation and inverse requests."""

    def _init_history(self) -> None:
        """Attach a dock without changing the main grid selection."""
        self._pending_history = None
        self._restoring_history = None
        self._history = self._review_store.history
        errors = self._history.reconcile()
        self.operation_history = HistoryPanel(
            self._history, self._history_host
        )
        self._history_host.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            self.operation_history,
        )
        self.operation_history.hide()
        self.operation_history_button = QtWidgets.QPushButton(
            self.tr("Operation history")
        )
        self.operation_history_button.clicked.connect(
            lambda: self.operation_history.setVisible(
                not self.operation_history.isVisible()
            )
        )
        self._history_host.centralWidget().layout().addWidget(
            self.operation_history_button
        )
        self.operation_history.locate_requested.connect(self._history_locate)
        self.operation_history.preview_requested.connect(self._history_preview)
        self.operation_history.return_requested.connect(self._history_return)
        self.operation_history.restore_requested.connect(self._history_restore)
        self.operation_history.revert_requested.connect(self._history_revert)
        self.operation_history.import_requested.connect(self.history_import_requested)
        if errors:
            self.operation_history.message.setText("\n".join(errors))

    def history_view(self) -> dict:
        """Capture reading context separately from candidates and bookmarks."""
        view = dict(
            label=self._selected_label,
            page=self._page,
            query=asdict(self._query_options),
        )
        for row, ref in enumerate(self._model._items):
            rect = self.view.visualRect(self._model.index(row, 0))
            if rect.intersects(self.view.viewport().rect()):
                view.update(
                    anchor=list(identity(ref)), pixel_offset=rect.top()
                )
                break
        return view

    def import_history_backups(self, root: str, resolver: object) -> None:
        """Make old backups discoverable through an explicit bounded scan."""
        try:
            count = self._history.import_backups(root, resolver)
            self.operation_history.refresh()
            self.operation_history.message.setText(self.tr("Imported %1 backup operation(s).").replace("%1", str(count)))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            self.operation_history.message.setText(str(exc))

    def begin_history(self, plan: object) -> dict:
        """Freeze a durable request before starting the existing relabel flow."""
        items = [
            dict(
                image_path=ref.image_id,
                json_path=path,
                shape_id=ref.shape_id,
                before=ref.display_summary,
                after=plan.target_label,
                status="pending",
            )
            for path, refs in plan.targets_by_annotation_path.items()
            for ref in refs
        ]
        parent = ""
        if plan.undo_record is not None:
            row = self._history.connection.execute(
                "SELECT id FROM thumbnail_history WHERE json_extract(payload,'$.items[0].image_path')=? "
                "AND json_extract(payload,'$.items[0].shape_id')=? "
                "AND json_extract(payload,'$.items[0].status')='succeeded' "
                "AND state IN ('completed','partial') ORDER BY created DESC LIMIT 1",
                (plan.undo_record.ref.image_id, plan.undo_record.ref.shape_id),
            ).fetchone()
            parent = row[0] if row else ""
        self._pending_history = self._history.begin(
            "undo" if plan.undo_record else "relabel",
            items,
            self.history_view(),
            parent,
        )
        self.operation_history.refresh()
        return self._pending_history

    def finish_history(self, result: object) -> None:
        """Index terminal evidence without turning successful saves into failures."""
        record = getattr(result, "history_record", None)
        if not record:
            return
        try:
            self._history.finish(copy.deepcopy(record))
            self._pending_history = None
            self.operation_history.refresh()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.advanced.feedback.setText(
                self.tr("Annotations saved; history needs reconciliation.")
                + " "
                + str(exc)
            )

    def history_save_snapshot(self, path: str) -> str:
        """Capture disk content before a managed canvas save."""
        try:
            return document_digest(read_document(path))
        except (OSError, ValueError):
            return ""

    def observe_transaction_result(self, result: object) -> None:
        """Track managed writes from other entries without adding history rows."""
        if getattr(result, "history_record", None):
            self.finish_history(result)
            return
        try:
            if not result.manifest_path:
                return
            with open(result.manifest_path, encoding="utf-8") as stream:
                entries = json.load(stream).get("entries", [])
            with self._history.connection:
                for entry in entries:
                    evidence = entry.get("domain_metadata", {}).get("history_document")
                    if entry.get("status") == "succeeded" and evidence:
                        self._history.observe_values(entry["source_path"], evidence["before_digest"],
                                                     evidence["after_digest"], evidence["labels"])
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.operation_history.message.setText(str(exc))

    def history_flow_stopped(self, message: str, cancelled: bool = False) -> None:
        """Leave an inspectable terminal or uncertain request after early exit."""
        record = self._pending_history
        if record is None:
            return
        record = dict(record)
        record["state"] = "cancelled" if cancelled else "unverified"
        record["items"] = [dict(i, status=record["state"], message=message) for i in record["items"]]
        try:
            self._history.finish(record)
            self.operation_history.refresh()
        except (OSError, sqlite3.Error) as exc:
            self.operation_history.message.setText(str(exc))
        self._pending_history = None

    def history_observe_save(self, path: str, before: str) -> None:
        """Preserve field evidence for known geometry-only canvas edits."""
        try:
            with self._history.connection:
                self._history.observe(path, before, read_document(path))
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.advanced.feedback.setText(
                self.tr("History revision could not be verified.")
                + " "
                + str(exc)
            )

    def _history_ref(self, item: dict) -> object:
        """Resolve current geometry by identity, independent of the old filter."""
        if not self._index_is_ready():
            raise ValueError(
                self.tr("Scan the index before locating history objects.")
            )
        location = self._controller.query_thumbnail_location(
            item["image_path"], item["shape_id"]
        )
        if location is None:
            raise ValueError(
                self.tr("Object missing or identity is not unique.")
            )
        page = self._query_page(
            location.label,
            100,
            location.offset // 100 * 100,
            (item["image_path"], item["shape_id"]),
            ThumbnailQuery(),
        )
        return next(
            (
                r
                for r in page.items
                if identity(r)
                == (
                    osp.normcase(osp.abspath(item["image_path"])),
                    item["shape_id"],
                )
            ),
            None,
        )

    def _history_locate(self, item: dict) -> None:
        """Navigate only on an explicit history action."""
        try:
            ref = self._history_ref(item)
            if ref is None:
                raise ValueError(
                    self.tr("Object missing or identity is not unique.")
                )
            self.navigate_requested.emit(ref)
        except (ValueError, sqlite3.Error) as exc:
            self.operation_history.message.setText(str(exc))

    def _history_preview(self, item: dict) -> None:
        """Label the preview as current image content, not a historical photo."""
        try:
            ref = self._history_ref(item)
            if ref is None:
                raise ValueError(
                    self.tr("Object missing or identity is not unique.")
                )
            dialog = ThumbnailPreview(
                ref,
                self._renderer.disk.root,
                self.advanced.render_options(),
                self,
            )
            dialog.setWindowTitle(self.tr("Preview current image"))
            dialog.show()
            self._history_preview_window = dialog
        except (ValueError, sqlite3.Error, OSError) as exc:
            self.operation_history.message.setText(str(exc))

    def _history_return(self, record: dict) -> None:
        """Restore explicit historical reading context without old candidates."""
        view = record.get("view", {})
        if not view.get("label") or not self._index_is_ready():
            return
        self._query_options = ThumbnailQuery.from_dict(view.get("query"))
        self.advanced.query = self._query_options
        self.advanced._search_timer.stop()
        for control, value in (
            (self.advanced.filename, self._query_options.filename),
            (self.advanced.sort, self._query_options.sort),
            (self.advanced.review_filter, self._query_options.review),
        ):
            blocker = QtCore.QSignalBlocker(control)
            if isinstance(control, QtWidgets.QLineEdit):
                control.setText(value)
            else:
                control.setCurrentIndex(control.findData(value))
            del blocker
        self._selected_label = view["label"]
        self._sync_label_counts()
        self._restore_view = dict(view)
        self._load_page()
        self.view.clearSelection()

    def _history_restore(self, record: dict) -> None:
        """Resolve a historical manifest before emitting the existing recovery action."""
        if not self._mutation_is_available():
            return
        manifest = record.get("manifest_path", "")
        candidates = [
            i
            for i in record["items"]
            if i.get("status") == "succeeded"
            and not self._history.consumed(record["id"], i)
        ]
        if (
            not manifest
            or not osp.isfile(manifest)
            or not candidates
            or record["state"] in ("pending", "unverified")
        ):
            self.operation_history.message.setText(
                self.tr("No verified backup recovery is available.")
            )
            return
        self.operation_history.message.setText(
            self.tr("File-level recovery:")
            + "\n"
            + "\n".join(sorted({i["json_path"] for i in candidates}))
        )
        self._restoring_history = self._history.begin(
            "restore",
            [
                dict(
                    i,
                    before=i.get("after"),
                    after=i.get("before"),
                    status="pending",
                )
                for i in candidates
            ],
            self.history_view(),
            record["id"],
        )
        self._restoring_history["manifest_path"] = manifest
        write_journal(self._restoring_history)
        self.restore_requested.emit(manifest)

    def finish_restore_history(self, result: object) -> None:
        """Record actual file outcomes while preserving the original operation."""
        if not self._restoring_history:
            return
        record = self._restoring_history
        statuses = {
            osp.normcase(osp.abspath(i.source_path)): i for i in result.files
        }
        record["documents"] = {}
        for item in record["items"]:
            outcome = statuses.get(
                osp.normcase(osp.abspath(item["json_path"]))
            )
            item["status"] = outcome.status if outcome else "unverified"
            item["message"] = outcome.message if outcome else ""
            if item["status"] == "succeeded":
                self.history_observe_save(item["json_path"], "")
        record["state"] = (
            "completed"
            if all(i["status"] == "succeeded" for i in record["items"])
            else "partial"
        )
        try:
            self._history.finish(record)
            self._restoring_history = None
            self.operation_history.refresh()
        except (OSError, sqlite3.Error) as exc:
            self.operation_history.message.setText(str(exc))

    def abort_restore_history(self, cancelled: bool) -> None:
        """Keep cancelled or uncertain recovery requests visible for inspection."""
        record = self._restoring_history
        if record is None:
            return
        record["state"] = "cancelled" if cancelled else "unverified"
        for item in record["items"]:
            item["status"] = record["state"]
        try:
            self._history.finish(record)
            self.operation_history.refresh()
        except (OSError, sqlite3.Error) as exc:
            self.operation_history.message.setText(str(exc))
        self._restoring_history = None

    def _history_revert(self, record: dict, items: list) -> None:
        """Request a guarded inverse without sharing the canvas undo stack."""
        if not self._mutation_is_available() or record["state"] in (
            "pending",
            "unverified",
        ):
            return
        if (
            QtWidgets.QMessageBox.question(
                self,
                self.tr("Revert selected changes"),
                "\n".join(
                    f'{i["image_path"]} #{i["shape_id"]}: {i.get("after")} → {i.get("before")}'
                    for i in items
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return
        if record["kind"] in ("review", "review-revert"):
            try:
                refs = tuple(
                    r for i in items if (r := self._history_ref(i)) is not None
                )
                self._review_store.revert(record["id"], items, refs)
                self.operation_history.refresh()
                self._sync_page()
            except (ValueError, sqlite3.Error) as exc:
                self.operation_history.message.setText(str(exc))
        else:
            self.history_revert_requested.emit(record, items)
