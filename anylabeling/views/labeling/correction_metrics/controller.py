"""Owns one correction-statistics session for a labeling window.

The controller is the only object the label widget talks to through
``notify_metrics``.  It stays importable without Qt so the wiring can be
exercised head-lessly: Qt-specific parts (heartbeat timer, foreground state)
are injected through ``heartbeat`` / ``clock_adapter`` callables.

Responsibilities, in the order the workflow uses them:

* enable a dataset scope and open the local statistics database only then;
* freeze a per-image starting point and keep the round in memory;
* translate the observer operations into round transactions / save
  checkpoints / review records, never inventing user edits;
* keep application time in ``WorkClock`` and write absolute snapshots;
* expose rows for the panel and the report dialog and degrade loudly instead
  of breaking annotation saving.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from anylabeling.services.correction_metrics import export, reporting
from anylabeling.services.correction_metrics.core import (
    SHAPE_ID,
    path_identity,
    safe_provenance,
)
from anylabeling.services.correction_metrics.storage import MetricsStore
from anylabeling.services.correction_metrics.timing import WorkClock

from .hooks import metrics_available, metrics_pending_message


def default_storage_root():
    """Local application-data directory for the statistics databases."""
    override = os.environ.get("XANYLABELING_METRICS_DIR")
    if override:
        return Path(override)
    base = Path.home() / ".xanylabeling"
    return base / "correction_metrics"


def content_digest(path, limit=64 * 1024 * 1024):
    """Stable content identity for one image file, independent of its path."""
    try:
        stat = os.stat(path)
        if stat.st_size > limit:
            return "size:%d:mtime:%d" % (stat.st_size, int(stat.st_mtime))
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def shape_ids(shapes):
    ids = []
    for shape in shapes or ():
        value = (
            shape.get(SHAPE_ID)
            if isinstance(shape, dict)
            else getattr(shape, "xanylabeling_shape_id", None)
        )
        if isinstance(value, str) and value and value not in ids:
            ids.append(value)
    return ids


class CorrectionMetricsController:
    """Session-scoped coordinator; create one per labeling window."""

    def __init__(
        self,
        host=None,
        *,
        language="en_US",
        storage_root=None,
        clock=None,
        idle_seconds=120,
        heartbeat=None,
        clock_adapter=None,
    ):
        self.host = host
        self.language = language
        self.storage_root = Path(storage_root or default_storage_root())
        self._clock = clock or WorkClock(idle_seconds=idle_seconds)
        self._heartbeat = heartbeat
        self._clock_adapter = clock_adapter
        self._store = None
        self._round = None
        self._scope = None
        self._enabled = False
        self._degraded = {}
        self._closed = False
        self._last_second = None
        self._saved_batches = set()

    # ---------------------------------------------------------- capability
    @property
    def available(self):
        return metrics_available()

    @property
    def enabled(self):
        return bool(
            self._enabled and self._store is not None and self._round is not None
        )

    @property
    def degraded_reason(self):
        if not self._degraded:
            return None
        operation = sorted(self._degraded)[-1]
        return "%s: %s" % (operation, self._degraded[operation])

    def degrade(self, operation, error=None):
        """Record an observer failure; annotation saving must keep working."""
        self._degraded[str(operation)] = str(error or "unknown error")
        if self._round is not None:
            self._round.mark_gap("metrics-observer-error")

    def pending_message(self):
        return metrics_pending_message(self.language)

    def state(self):
        totals = self._clock.totals
        return {
            "state": self._clock.state,
            "seconds": float(totals.get("working", 0.0)),
            "paused": bool(self._clock.paused),
            "idle_waiting": bool(totals.get("pending_idle")),
            "degraded": self.degraded_reason,
        }

    # ------------------------------------------------------------- scope
    def start_scope(self, image_root, label_root=None):
        """Enable statistics for one dataset and open its local database."""
        if self._closed or self._store is not None:
            return self._store is not None
        if not image_root:
            return False
        scope = (str(image_root), str(label_root or image_root))
        try:
            self._store = MetricsStore(self._database_path(scope[0], scope[1]))
            if self._store.error:
                self.degrade("start_scope", self._store.error)
                self._store.close()
                self._store = None
                return False
        except Exception as error:  # noqa: BLE001 - degrade, never crash
            self.degrade("start_scope", error)
            self._store = None
            return False
        self._scope = scope
        self._enabled = True
        self._set_prediction_collection(True)
        if self._heartbeat is not None:
            try:
                self._heartbeat(self.tick)
            except Exception as error:  # noqa: BLE001
                self.degrade("start_scope", error)
        return True

    def _database_path(self, image_root, label_root):
        from anylabeling.services.correction_metrics.core import dataset_identity

        identity = dataset_identity(image_root, label_root)
        return self.storage_root / ("%s.sqlite3" % identity)

    def _start_scope_for(self, image_path):
        image_root = os.path.dirname(os.fspath(image_path))
        label_root = getattr(self.host, "output_dir", None) or image_root
        return self.start_scope(image_root, label_root)

    def _set_prediction_collection(self, enabled):
        """Collect prediction provenance only while statistics are enabled."""
        try:
            from anylabeling.services.auto_labeling.model_manager import (
                enable_prediction_provenance,
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("prediction_provenance", error)
            return False
        widget = getattr(self.host, "auto_labeling_widget", None)
        manager = getattr(widget, "model_manager", None)
        if manager is None:
            return False
        return enable_prediction_provenance(manager, enabled)

    def taxonomy_saved(self, image_path, label_path=None, shapes=None,
                       mapping=None, comparable=True):
        """Record a confirmed global class migration for one saved label file.

        Called by ``LabelModifyDialog.modify_label`` after it rewrote a label
        file.  Only images that already take part in the statistics are
        touched: an image without a round is skipped, never given a new round,
        so a bulk rename cannot pollute the report with historical files.
        """
        mapping = dict(mapping or {})
        image = os.fspath(image_path) if image_path else None
        label = os.fspath(label_path) if label_path else None
        if not image or not label:
            return False
        target = self._round if self._matches_current(image, label) else None
        if target is None and self._store is not None:
            try:
                target = self._store.latest(image, label)
            except Exception as error:  # noqa: BLE001
                self.degrade("taxonomy_saved", error)
                return False
        if target is None:
            return False
        try:
            return target.taxonomy(
                mapping, comparable=comparable, shapes=shapes
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("taxonomy_saved", error)
            return False

    def _matches_current(self, image_path, label_path):
        if self._round is None:
            return False
        try:
            return (
                path_identity(image_path) == self._round.image_path
                and path_identity(label_path) == self._round.label_path
            )
        except Exception:  # noqa: BLE001
            return False

    def stop(self):
        """Flush timing and close the database; safe to call twice."""
        if self._closed:
            return
        if self._round is not None:
            self._save_time(closed=True)
            self._round = None
        if self._store is not None:
            try:
                self._store.flush()
            except Exception as error:  # noqa: BLE001
                self.degrade("stop", error)
            self._store.close()
            self._store = None
        if self._clock_adapter is not None:
            try:
                self._clock_adapter.stop()
            except Exception as error:  # noqa: BLE001
                self.degrade("stop", error)
        timer = getattr(self, "heartbeat_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception as error:  # noqa: BLE001
                self.degrade("stop", error)
        self._set_prediction_collection(False)
        self._closed = True
        self._enabled = False

    # ------------------------------------------------------- current image
    def enter_image(self):
        """Freeze the starting point of the image now shown, on first entry."""
        if self._closed:
            return False
        path = self._image_path()
        if not path:
            return False
        if self._store is None and not self._start_scope_for(path):
            return False
        label = self._label_path(path)
        shapes = self._shapes()
        try:
            # ``open_round`` reuses the same round for an unchanged image and
            # flags its own gaps (image-content-changed, interrupted draft);
            # reopening must never look like an incomplete round by itself.
            self._round = self._store.open_round(
                path,
                label,
                content_digest(path),
                shapes,
                origin="unknown-existing",
                saved=True,
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("enter_image", error)
            self._round = None
            return False
        self._clock.attach(self._round.round_id, ready=True)
        self._last_second = None
        self.tick()
        return True

    def leave_image(self):
        """Close the working interval and flush before another image loads."""
        if self._round is None and self._store is None:
            return False
        if self._round is not None:
            self._save_time(closed=True)
            self._clock.attach(None)
            self._round = None
        if self._store is not None:
            self._store.flush()
        return True

    # ------------------------------------------------------- edit observers
    def edit(self, kind, source="manual", changed=None, removed=None,
             transaction_id=None, undo_of=None):
        if not self.enabled:
            return False
        try:
            return self._round.patch(
                shapes=list(changed or ()),
                removed_ids=shape_ids(removed),
                kind=kind,
                source=source,
                transaction_id=transaction_id,
                undo_of=undo_of,
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("edit", error)
            return False

    def geometry(self):
        """Legacy geometry signal without object identity: disclose, don't guess."""
        if not self.enabled:
            return False
        self._round.mark_gap("unidentified-geometry")
        return True

    def review_event(self, kind, affected_ids=(), transaction_id=None):
        if not self.enabled:
            return False
        try:
            return self._round.review_event(
                kind, affected_ids, transaction_id=transaction_id
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("review_event", error)
            return False

    def reconcile_dirty(self):
        """Refresh trigger only: ``set_dirty`` is not an operation ledger."""
        return self.current_row(draft=True) is not None

    # -------------------------------------------------------------- saving
    def prepare_save(self, filename=None, shapes=None):
        if not self.enabled:
            return None
        try:
            return self._round.prepare_save(
                list(shapes if shapes is not None else self._shapes()),
                self._resolve_target(filename),
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("prepare_save", error)
            return None

    def save_result(self, token, succeeded):
        if not self.enabled:
            return False
        try:
            if succeeded:
                return self._round.saved(token)
            self._round.save_failed(token)
            return False
        except Exception as error:  # noqa: BLE001
            self.degrade("save_result", error)
            return False

    def discard(self):
        if not self.enabled:
            return False
        try:
            return self._round.discard()
        except Exception as error:  # noqa: BLE001
            self.degrade("discard", error)
            return False

    # ---------------------------------------------------------- predictions
    def prediction_applied(self, result=None):
        """Start a new round for an applied prediction, keeping old rounds."""
        if self._closed or self._store is None:
            return False
        path = self._image_path()
        if not path:
            return False
        provenance = dict(getattr(result, "provenance", None) or {})
        mode = provenance.get("mode") or "replacement"
        origin = "additive" if mode == "additive" else "replacement"
        # Only the objects this run predicted become AI objects.  The canvas
        # holds retained manual boxes too, so using it would count 5 manual
        # boxes as predicted (8 instead of 3 in the "5+3" scenario).
        predicted_shapes = getattr(result, "shapes", None)
        predicted = shape_ids(
            predicted_shapes if predicted_shapes is not None else self._shapes()
        )
        try:
            self._round = self._store.open_round(
                path,
                self._label_path(path),
                content_digest(path),
                self._shapes(),
                origin=origin,
                provenance=provenance,
                predicted_ids=predicted,
                saved=False,
                force_new=True,
            )
            self._store.record_prediction(
                path, self._label_path(path), provenance, "applied"
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("prediction_applied", error)
            return False
        self._clock.attach(self._round.round_id, ready=True)
        return True

    def prediction_unapplied(self, image_path, provenance=None):
        if self._store is None or not image_path:
            return False
        try:
            label = self._label_path(image_path)
            self._store.record_prediction(
                image_path, label, dict(provenance or {}), "unapplied"
            )
            return True
        except Exception as error:  # noqa: BLE001
            self.degrade("prediction_unapplied", error)
            return False

    def prediction_saved(self, image_path, label_path=None, provenance=None,
                         shapes=None, status="applied"):
        """Batch predictions write JSON directly: record one image at a time.

        Unlike ``prediction_applied`` this never touches the round of the
        currently open image, never starts human timing and never completes the
        image.  Only an actually saved file becomes a baseline.
        """
        if self._store is None or not image_path:
            return False
        source = safe_provenance(dict(provenance or {}))
        label = label_path or self._label_path(image_path)
        # Batch calls come from a worker thread and may be retried: remember
        # the (image, label, run) keys so a repeated call cannot open a second
        # round for the same saved file.
        key = (path_identity(image_path), path_identity(label), source.get("run_id"))
        if key[2] and key in self._saved_batches:
            return True
        try:
            if status == "applied":
                mode = source.get("mode") or "replacement"
                self._store.open_round(
                    image_path,
                    label,
                    content_digest(image_path),
                    list(shapes or ()),
                    origin="additive" if mode == "additive" else "replacement",
                    provenance=source,
                    predicted_ids=shape_ids(shapes),
                    saved=True,
                    force_new=True,
                )
                if key[2]:
                    if len(self._saved_batches) > 4096:
                        self._saved_batches.clear()
                    self._saved_batches.add(key)
            self._store.record_prediction(image_path, label, source, status)
            # No flush here: this runs on the batch worker thread and the queue
            # drains later; the report flushes before reading.
            return True
        except Exception as error:  # noqa: BLE001
            self.degrade("prediction_saved", error)
            return False

    # --------------------------------------------------------------- timing
    def tick(self, seconds=None):
        """Advance the work clock and persist a coarse heartbeat."""
        if self._round is None:
            return None
        self._clock.tick()
        total = self._clock.totals["working"]
        if self._last_second is None or total - self._last_second >= 1.0:
            self._save_time()
            self._last_second = total
        return self.state()

    def pause(self, value=True):
        self._clock.change(paused=bool(value))
        self._save_time()
        return self.state()

    def use_clock_adapter(self, adapter):
        """Let the Qt adapter own the work clock (foreground, suspend, idle)."""
        self._clock_adapter = adapter
        self._clock = adapter.work
        timer = getattr(self, "heartbeat_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception as error:  # noqa: BLE001
                self.degrade("clock_adapter", error)

    def time_checkpoint(self, round_id, session_id, totals, closed):
        """Adapter callback: an absolute snapshot, never an increment."""
        if self._round is None or self._round.round_id != round_id:
            return False
        try:
            audit = (
                self._clock_adapter.audit
                if self._clock_adapter is not None
                else self._clock.audit
            )
            self._round.set_time(
                session_id, totals, closed=closed, audit=audit
            )
            return True
        except Exception as error:  # noqa: BLE001
            self.degrade("set_time", error)
            return False

    def confirm_idle(self, exclude=True):
        self._clock.confirm_idle(bool(exclude))
        self._save_time()
        return self.state()

    def _save_time(self, closed=False):
        if self._round is None:
            return
        try:
            self._round.set_time(
                self._clock.session_id or self._store.session_id,
                self._clock.totals,
                closed=closed,
                audit=self._clock.audit,
            )
        except Exception as error:  # noqa: BLE001
            self.degrade("set_time", error)

    # ------------------------------------------------------------ completion
    def finish_round(self):
        if not self.enabled:
            return False
        try:
            return self._round.finish()
        except Exception as error:  # noqa: BLE001
            self.degrade("finish_round", error)
            return False

    def resume_round(self):
        if not self.enabled:
            return False
        try:
            return self._round.resume()
        except Exception as error:  # noqa: BLE001
            self.degrade("resume_round", error)
            return False

    # -------------------------------------------------------------- queries
    def current_row(self, draft=True):
        if self._round is None:
            return None
        try:
            return self._round.row(draft=draft)
        except Exception as error:  # noqa: BLE001
            self.degrade("current_row", error)
            return None

    def rows(self, limit=None, offset=0):
        if self._store is None:
            return []
        try:
            # A read must include the checkpoints queued by the current session.
            self._store.flush()
            return [
                reporting.saved_row(row)
                for row in self._store.iter_rows(limit, offset)
            ]
        except Exception as error:  # noqa: BLE001
            self.degrade("rows", error)
            return []

    def count(self):
        if self._store is None:
            return 0
        try:
            self._store.flush()
            return self._store.count()
        except Exception as error:  # noqa: BLE001
            self.degrade("count", error)
            return 0

    def export(self, kind, path, cancelled=None, progress=None, rows=None):
        """Export a CSV; ``rows`` freezes the caller's on-screen snapshot."""
        selected = self.rows() if rows is None else list(rows)
        return export.export_csv(path, selected, kind, cancelled=cancelled,
                                 progress=progress)

    # ---------------------------------------------------------- host bridge
    def _image_path(self):
        value = getattr(self.host, "filename", None)
        return os.fspath(value) if value else None

    def _shapes(self):
        canvas = getattr(self.host, "canvas", None)
        return list(getattr(canvas, "shapes", None) or ())

    def _label_path(self, image_path):
        if not image_path:
            return ""
        output_dir = getattr(self.host, "output_dir", None)
        stem = os.path.splitext(os.path.basename(image_path))[0]
        name = stem + ".json"
        if output_dir:
            return os.path.join(os.fspath(output_dir), name)
        return os.path.join(os.path.dirname(image_path), name)

    def _resolve_target(self, filename):
        """Match the observer's filename to this round's label path.

        The hook passes whatever the save routine is about to write; it has to
        resolve to the identical absolute path, otherwise ``CorrectionRound``
        treats the call as a real "save as" fork and opens a second round.
        """
        default = self._label_path(self._image_path())
        if not filename:
            return default
        raw = os.fspath(filename)
        if not os.path.isabs(raw):
            raw = os.path.join(os.path.dirname(default), os.path.basename(raw))
        return raw

    # ------------------------------------------------------------ panel glue
    def show_panel(self):
        """Create or raise the compact panel; never block annotation work."""
        panel = getattr(self, "panel", None)
        if panel is None:
            panel = self._build_panel()
            self.panel = panel
        if panel is None:
            return False
        try:
            panel.refresh_with(self.current_row(draft=True), self.state())
            panel.set_collapsed(False)
            panel.show()
            panel.raise_()
            return True
        except Exception as error:  # noqa: BLE001 - UI failure must not crash
            self.degrade("show_panel", error)
            return False

    def show_summary(self):
        dialog = getattr(self, "report_dialog", None)
        if dialog is None:
            dialog = self._build_report_dialog()
            self.report_dialog = dialog
        if dialog is None:
            return False
        try:
            dialog.refresh()
            dialog.show()
            dialog.raise_()
            return True
        except Exception as error:  # noqa: BLE001
            self.degrade("show_summary", error)
            return False

    def _build_panel(self):
        try:
            from .panel import CorrectionMetricsPanel

            panel = CorrectionMetricsPanel(self, parent=self.host)
            panel.pause_requested.connect(self.pause)
            panel.finish_requested.connect(self.finish_round)
            panel.summary_requested.connect(self.show_summary)
            return panel
        except Exception as error:  # noqa: BLE001
            self.degrade("panel", error)
            return None

    def _build_report_dialog(self):
        try:
            from .report_dialog import ReportDialog

            return ReportDialog(self, parent=self.host)
        except Exception as error:  # noqa: BLE001
            self.degrade("report_dialog", error)
            return None

    def refresh_panel(self):
        panel = getattr(self, "panel", None)
        if panel is None:
            return False
        try:
            panel.refresh_with(self.current_row(draft=True), self.state())
            return True
        except Exception as error:  # noqa: BLE001
            self.degrade("refresh_panel", error)
            return False


def start_metrics(host):
    """Entry point used by the labeling menu: create and enable the session."""
    controller = getattr(host, "correction_metrics", None)
    if controller is None:
        controller = CorrectionMetricsController(
            host, language=getattr(host, "_config", {}).get("language", "en_US")
        )
        host.correction_metrics = controller
    _install_clock_adapter(host, controller)
    image_path = getattr(host, "filename", None)
    if image_path and not controller.enabled:
        controller.start_scope(
            os.path.dirname(os.fspath(image_path)),
            getattr(host, "output_dir", None)
            or os.path.dirname(os.fspath(image_path)),
        )
        controller.enter_image()
    _install_heartbeat(host, controller)
    controller.show_panel()
    return controller


def _install_clock_adapter(host, controller):
    """Prefer the Qt clock: it knows foreground, idle and session changes."""
    if getattr(controller, "_clock_adapter", None) is not None:
        return controller._clock_adapter
    try:
        from .clock_adapter import QtClockAdapter

        adapter = QtClockAdapter(
            host, controller.time_checkpoint, idle_seconds=120
        )
        controller.use_clock_adapter(adapter)
        return adapter
    except Exception as error:  # noqa: BLE001 - head-less hosts keep the plain clock
        controller.degrade("clock_adapter", error)
        return None


def _install_heartbeat(host, controller):
    """Drive the work clock once per second; harmless without Qt."""
    if getattr(controller, "_clock_adapter", None) is not None:
        return None  # the Qt adapter already runs its own precise heartbeat
    timer = getattr(controller, "heartbeat_timer", None)
    if timer is not None:
        if not timer.isActive():
            timer.start()
        return timer
    try:
        from PyQt6.QtCore import QTimer

        timer = QTimer(host)
        timer.setInterval(1000)
        timer.timeout.connect(controller.tick)
        timer.start()
        controller.heartbeat_timer = timer
        return timer
    except Exception as error:  # noqa: BLE001 - head-less / non-Qt host
        controller.degrade("heartbeat", error)
        return None
