"""Paged summary and CSV export for correction-cost statistics (design D7).

The dialog is deliberately read-only.  Every number it shows comes from
``anylabeling.services.correction_metrics.reporting`` over **one** snapshot of
``controller.rows()``: refreshing freezes a new list, and later edits by the
user never change what the current report says.  Nothing here recomputes a
metric that the reporting module already owns.

Exports go through ``controller.export()`` and therefore through
``services/correction_metrics/export.py``: the CSV is written to a temporary
file next to the destination and only published with ``os.replace`` after a
final cancellation check, so a cancelled or failed export can never leave a
file that looks like a successful one.  The write runs on a ``QThread``; the
GUI thread only receives progress numbers and a terminal signal.

Strings live in ``_STRINGS`` below so this file can be delivered before the
shared catalog is extended; ``_tr()`` prefers the shared ``i18n`` catalog and
falls back to the local table when a key is missing there.
"""

from __future__ import annotations

import os
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from anylabeling.services.correction_metrics import export as export_module
from anylabeling.services.correction_metrics import reporting

__all__ = ("ReportDialog", "PAGE_SIZE")

PAGE_SIZE = 50
NA = "N/A"

#: Keys this dialog renders itself.  ``i18n.py`` already covers the general
#: vocabulary (titles, columns that existed in the panel, yes/no, ...); the
#: entries below are the keys the dialog adds, in all four UI languages.
_STRINGS = {
    "rounds_phases": {
        "en_US": "Rounds {rounds} \u00b7 correction {correction} \u00b7 review {review}",
        "zh_CN": "\u8f6e\u6b21 {rounds} \u00b7 \u4fee\u6b63 {correction} \u00b7 \u590d\u6838 {review}",
        "ja_JP": "\u30e9\u30a6\u30f3\u30c9 {rounds} \u00b7 \u4fee\u6b63 {correction} \u00b7 \u30ec\u30d3\u30e5\u30fc {review}",
        "ko_KR": "\ub77c\uc6b4\ub4dc {rounds} \u00b7 \uc218\uc815 {correction} \u00b7 \uac80\ud1a0 {review}",
    },
    "excluded_total": {
        "en_US": "Excluded rounds: {count}",
        "zh_CN": "\u5df2\u6392\u9664\u8f6e\u6b21\uff1a{count}",
        "ja_JP": "\u9664\u5916\u30e9\u30a6\u30f3\u30c9\uff1a{count}",
        "ko_KR": "\uc81c\uc678\ub41c \ub77c\uc6b4\ub4dc: {count}",
    },
    "excluded_none": {
        "en_US": "Nothing excluded",
        "zh_CN": "\u6ca1\u6709\u6392\u9664\u9879",
        "ja_JP": "\u9664\u5916\u306f\u3042\u308a\u307e\u305b\u3093",
        "ko_KR": "\uc81c\uc678 \ud56d\ubaa9 \uc5c6\uc74c",
    },
    "image_count": {
        "en_US": "Images",
        "zh_CN": "\u56fe\u7247\u6570",
        "ja_JP": "\u753b\u50cf\u6570",
        "ko_KR": "\uc774\ubbf8\uc9c0 \uc218",
    },
    "unchanged": {
        "en_US": "Unchanged boxes",
        "zh_CN": "\u672a\u53d8\u6846\u6570",
        "ja_JP": "\u672a\u5909\u66f4\u30dc\u30c3\u30af\u30b9",
        "ko_KR": "\ubcc0\uacbd \uc5c6\ub294 \ubc15\uc2a4",
    },
    "touches": {
        "en_US": "Touches",
        "zh_CN": "\u89e6\u8fbe\u6b21\u6570",
        "ja_JP": "\u30bf\u30c3\u30c1\u6570",
        "ko_KR": "\ud130\uce58 \uc218",
    },
    "unique_objects": {
        "en_US": "Unique objects",
        "zh_CN": "\u53bb\u91cd\u5bf9\u8c61\u6570",
        "ja_JP": "\u4e00\u610f\u30aa\u30d6\u30b8\u30a7\u30af\u30c8\u6570",
        "ko_KR": "\uace0\uc720 \uac1d\uccb4 \uc218",
    },
    "comparable": {
        "en_US": "Comparable",
        "zh_CN": "\u53ef\u6bd4",
        "ja_JP": "\u6bd4\u8f03\u53ef\u80fd",
        "ko_KR": "\ube44\uad50 \uac00\ub2a5",
    },
    "review_phase": {
        "en_US": "Review",
        "zh_CN": "\u590d\u6838",
        "ja_JP": "\u30ec\u30d3\u30e5\u30fc",
        "ko_KR": "\uac80\ud1a0",
    },
    "export_images": {
        "en_US": "Image round details CSV\u2026",
        "zh_CN": "\u56fe\u7247\u8f6e\u6b21\u660e\u7ec6 CSV\u2026",
        "ja_JP": "\u753b\u50cf\u30e9\u30a6\u30f3\u30c9\u660e\u7d30 CSV\u2026",
        "ko_KR": "\uc774\ubbf8\uc9c0 \ub77c\uc6b4\ub4dc \uc0c1\uc138 CSV\u2026",
    },
    "export_classes": {
        "en_US": "Class change details CSV\u2026",
        "zh_CN": "\u7c7b\u522b\u53d8\u5316\u660e\u7ec6 CSV\u2026",
        "ja_JP": "\u30af\u30e9\u30b9\u5909\u66f4\u660e\u7d30 CSV\u2026",
        "ko_KR": "\ud074\ub798\uc2a4 \ubcc0\uacbd \uc0c1\uc138 CSV\u2026",
    },
    "export_dictionary": {
        "en_US": "Metric dictionary CSV\u2026",
        "zh_CN": "\u6307\u6807\u5b57\u5178 CSV\u2026",
        "ja_JP": "\u6307\u6a19\u8f9e\u66f8 CSV\u2026",
        "ko_KR": "\uc9c0\ud45c \uc0ac\uc804 CSV\u2026",
    },
    "export_cancelled": {
        "en_US": "Export cancelled; no file was written.",
        "zh_CN": "\u5bfc\u51fa\u5df2\u53d6\u6d88\uff0c\u672a\u5199\u5165\u6587\u4ef6\u3002",
        "ja_JP": "\u30a8\u30af\u30b9\u30dd\u30fc\u30c8\u3092\u4e2d\u6b62\u3057\u307e\u3057\u305f\u3002\u30d5\u30a1\u30a4\u30eb\u306f\u66f8\u304d\u8fbc\u307e\u308c\u3066\u3044\u307e\u305b\u3093\u3002",
        "ko_KR": "\ub0b4\ubcf4\ub0b4\uae30\ub97c \ucde8\uc18c\ud588\uc2b5\ub2c8\ub2e4. \ud30c\uc77c\uc744 \uc4f0\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.",
    },
    "export_failed": {
        "en_US": "Export failed: {error}",
        "zh_CN": "\u5bfc\u51fa\u5931\u8d25\uff1a{error}",
        "ja_JP": "\u30a8\u30af\u30b9\u30dd\u30fc\u30c8\u306b\u5931\u6557\u3057\u307e\u3057\u305f\uff1a{error}",
        "ko_KR": "\ub0b4\ubcf4\ub0b4\uae30 \uc2e4\ud328: {error}",
    },
    "export_busy": {
        "en_US": "Wait for the current export to finish.",
        "zh_CN": "\u8bf7\u7b49\u5f85\u5f53\u524d\u5bfc\u51fa\u5b8c\u6210\u3002",
        "ja_JP": "\u73fe\u5728\u306e\u30a8\u30af\u30b9\u30dd\u30fc\u30c8\u5b8c\u4e86\u3092\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002",
        "ko_KR": "\ud604\uc7ac \ub0b4\ubcf4\ub0b4\uae30\uac00 \ub05d\ub0a0 \ub54c\uae4c\uc9c0 \uae30\ub2e4\ub9ac\uc138\uc694.",
    },
    "sort_hint": {
        "en_US": "Click a column header to sort.",
        "zh_CN": "\u70b9\u51fb\u5217\u6807\u9898\u6392\u5e8f\u3002",
        "ja_JP": "\u5217\u30d8\u30c3\u30c0\u30fc\u3092\u30af\u30ea\u30c3\u30af\u3057\u3066\u4e26\u3079\u66ff\u3048\u307e\u3059\u3002",
        "ko_KR": "\uc5f4 \uba38\ub9ac\uae00\uc744 \ud074\ub9ad\ud574 \uc815\ub82c\ud569\ub2c8\ub2e4.",
    },
    "reason_unfinished": {
        "en_US": "Round unfinished",
        "zh_CN": "\u8f6e\u6b21\u672a\u5b8c\u6210",
        "ja_JP": "\u30e9\u30a6\u30f3\u30c9\u672a\u5b8c\u4e86",
        "ko_KR": "\ub77c\uc6b4\ub4dc \ubbf8\uc644\ub8cc",
    },
    "reason_incomplete": {
        "en_US": "Record incomplete",
        "zh_CN": "\u8bb0\u5f55\u4e0d\u5b8c\u6574",
        "ja_JP": "\u8a18\u9332\u304c\u4e0d\u5b8c\u5168",
        "ko_KR": "\uae30\ub85d \ubd88\uc644\uc804",
    },
    "reason_class_incomparable": {
        "en_US": "Class vocabulary not comparable",
        "zh_CN": "\u7c7b\u522b\u4f53\u7cfb\u4e0d\u53ef\u6bd4",
        "ja_JP": "\u30af\u30e9\u30b9\u4f53\u7cfb\u304c\u6bd4\u8f03\u4e0d\u53ef",
        "ko_KR": "\ud074\ub798\uc2a4 \uccb4\uacc4 \ube44\uad50 \ubd88\uac00",
    },
    "reason_unsaved_result": {
        "en_US": "Saved result pending",
        "zh_CN": "\u4fdd\u5b58\u7ed3\u679c\u5f85\u786e\u8ba4",
        "ja_JP": "\u4fdd\u5b58\u7d50\u679c\u306e\u78ba\u5b9a\u5f85\u3061",
        "ko_KR": "\uc800\uc7a5 \uacb0\uacfc \ub300\uae30 \uc911",
    },
    "reason_unknown_image_version": {
        "en_US": "Image version unknown",
        "zh_CN": "\u56fe\u7247\u7248\u672c\u672a\u77e5",
        "ja_JP": "\u753b\u50cf\u30d0\u30fc\u30b8\u30e7\u30f3\u4e0d\u660e",
        "ko_KR": "\uc774\ubbf8\uc9c0 \ubc84\uc804 \uc54c \uc218 \uc5c6\uc74c",
    },
    "reason_shape_identity_conflict": {
        "en_US": "Duplicate object identity",
        "zh_CN": "\u5bf9\u8c61\u6807\u8bc6\u91cd\u590d",
        "ja_JP": "\u30aa\u30d6\u30b8\u30a7\u30af\u30c8\u8b58\u5225\u5b50\u306e\u91cd\u8907",
        "ko_KR": "\uac1d\uccb4 \uc2dd\ubcc4\uc790 \uc911\ubcf5",
    },
    "reason_invalid_geometry": {
        "en_US": "Invalid geometry",
        "zh_CN": "\u51e0\u4f55\u6570\u636e\u65e0\u6548",
        "ja_JP": "\u7121\u52b9\u306a\u30b8\u30aa\u30e1\u30c8\u30ea",
        "ko_KR": "\uc798\ubabb\ub41c \uae30\ud558 \uc815\ubcf4",
    },
    "reason_type_conversion": {
        "en_US": "Shape type converted",
        "zh_CN": "\u5f62\u72b6\u7c7b\u578b\u5df2\u8f6c\u6362",
        "ja_JP": "\u56f3\u5f62\u30bf\u30a4\u30d7\u5909\u63db",
        "ko_KR": "\ub3c4\ud615 \uc720\ud615 \ubcc0\ud658",
    },
    "reason_unobserved_content_change": {
        "en_US": "Unobserved content change",
        "zh_CN": "\u672a\u89c2\u6d4b\u5230\u7684\u5185\u5bb9\u53d8\u5316",
        "ja_JP": "\u672a\u89b3\u6e2c\u306e\u5185\u5bb9\u5909\u66f4",
        "ko_KR": "\uad00\uce21\ub418\uc9c0 \uc54a\uc740 \ub0b4\uc6a9 \ubcc0\uacbd",
    },
    "reason_unidentified_geometry": {
        "en_US": "Unidentified geometry edit",
        "zh_CN": "\u65e0\u6cd5\u8bc6\u522b\u7684\u51e0\u4f55\u7f16\u8f91",
        "ja_JP": "\u7279\u5b9a\u4e0d\u80fd\u306a\u30b8\u30aa\u30e1\u30c8\u30ea\u7de8\u96c6",
        "ko_KR": "\uc2dd\ubcc4\ub418\uc9c0 \uc54a\uc740 \uae30\ud558 \ud3b8\uc9d1",
    },
    "reason_storage_gap": {
        "en_US": "Storage gap",
        "zh_CN": "\u5b58\u50a8\u7f3a\u53e3",
        "ja_JP": "\u4fdd\u5b58\u306e\u6b20\u843d",
        "ko_KR": "\uc800\uc7a5 \uacf5\ubc31",
    },
    "reason_reopened_round": {
        "en_US": "Round reopened",
        "zh_CN": "\u8f6e\u6b21\u5df2\u91cd\u65b0\u6253\u5f00",
        "ja_JP": "\u30e9\u30a6\u30f3\u30c9\u518d\u958b",
        "ko_KR": "\ub77c\uc6b4\ub4dc \ub2e4\uc2dc \uc5f4\ub9bc",
    },
    "reason_metrics_observer_error": {
        "en_US": "Statistics write failed",
        "zh_CN": "\u7edf\u8ba1\u5199\u5165\u5931\u8d25",
        "ja_JP": "\u7d71\u8a08\u306e\u66f8\u304d\u8fbc\u307f\u5931\u6557",
        "ko_KR": "\ud1b5\uacc4 \uc4f0\uae30 \uc2e4\ud328",
    },
    "reason_pending_checkpoint": {
        "en_US": "Save checkpoint pending",
        "zh_CN": "\u4fdd\u5b58\u68c0\u67e5\u70b9\u5f85\u786e\u8ba4",
        "ja_JP": "\u4fdd\u5b58\u30c1\u30a7\u30c3\u30af\u30dd\u30a4\u30f3\u30c8\u5f85\u3061",
        "ko_KR": "\uc800\uc7a5 \uccb4\ud06c\ud3ec\uc778\ud2b8 \ub300\uae30",
    },
}

#: English sources for catalog keys this dialog reuses.  ``i18n.tr`` can raise
#: (PyQt6 encodes ``QTranslator.translate`` sources as ASCII here, and several
#: catalog strings contain ``·``), so every key the dialog shows also has a
#: readable fallback; the local table never turns a label into a bare key id.
_FALLBACK = {
    "report_title": "Correction Cost Report",
    "refresh": "Refresh snapshot",
    "snapshot": "Snapshot {stamp}",
    "images": "Image rounds",
    "classes": "Class changes",
    "groups": "By density and model",
    "search": "Search image, class or model",
    "phase": "Stage",
    "round": "Round",
    "image_path": "Image",
    "origin": "Baseline source",
    "baseline_count": "Initial boxes",
    "final_count": "Saved boxes",
    "added": "Added",
    "deleted": "Deleted",
    "geometry_changed": "Geometry edits",
    "class_changed": "Class edits",
    "geometry": "Geometry",
    "transactions": "Operations",
    "working_seconds": "Processing (s)",
    "median_seconds": "Median seconds/round",
    "seconds_per_100": "Seconds / 100 boxes",
    "completed": "Completed",
    "quality": "Quality assessment",
    "not-assessed": "Not assessed",
    "issues": "Limitations",
    "clean": "No recorded gaps",
    "counts": "{images} completed image(s) · {eligible}/{rounds} comparable rounds",
    "images_count": "Distinct images",
    "excluded": "Excluded reasons",
    "group_note": (
        "Comparable saved rounds only. Density uses final rectangles. "
        "Sequential runs on the same image are dependent."
    ),
    "prev": "Previous page",
    "next": "Next page",
    "page": "Page {page}/{pages} · {count} rows",
    "export": "Export CSV…",
    "exporting": "Writing CSV…",
    "exported": "Exported {file}",
    "error": "Operation failed",
    "cancel": "Cancel",
    "close": "Close",
    "details": "Show details",
    "hide_details": "Hide details",
    "yes": "Yes",
    "no": "No",
    "model": "Model",
    "model_version": "Model version",
    "category_version": "Class vocabulary version",
    "kind": "Metric",
    "initial_class": "Initial class",
    "final_class": "Final class",
    "count": "Objects",
    "denominator": "Denominator",
    "modified_original": "Changed original boxes",
    "modified_rate": "Changed / initial",
    "density": "Final boxes per image",
    "initial": "Initial",
    "final": "Final",
    "unsaved": "Unsaved",
    "partial_scope": "Partial rectangle scope",
    "unknown_source": "Unknown source",
    "no_data": "No recorded image",
    "correction": "Correction",
    "replacement": "Replacement prediction",
    "additive": "Appended prediction",
    "unknown-existing": "Existing annotations, unknown source",
}

#: Exclusion reason / limitation codes mapped to a catalog key.  Codes that
#: are not listed here are shown verbatim instead of being hidden.
_REASON_KEYS = {
    "unsaved": "unsaved",
    "unfinished": "reason_unfinished",
    "incomplete": "reason_incomplete",
    "unknown-origin": "unknown_source",
    "partial-scope": "partial_scope",
    "class-incomparable": "reason_class_incomparable",
    "unsaved-result": "reason_unsaved_result",
    "unknown-image-version": "reason_unknown_image_version",
    "shape-identity-conflict": "reason_shape_identity_conflict",
    "invalid-geometry": "reason_invalid_geometry",
    "type-conversion": "reason_type_conversion",
    "unobserved-content-change": "reason_unobserved_content_change",
    "unidentified-geometry": "reason_unidentified_geometry",
    "storage-gap": "reason_storage_gap",
    "reopened-round": "reason_reopened_round",
    "metrics-observer-error": "reason_metrics_observer_error",
    "pending-checkpoint": "reason_pending_checkpoint",
}

#: ``(record key, header catalog key)`` pairs, in display order.
IMAGE_TABLE_COLUMNS = (
    ("image_path", "image_path"),
    ("round_id", "round"),
    ("phase", "phase"),
    ("origin", "origin"),
    ("baseline_count", "baseline_count"),
    ("final_count", "final_count"),
    ("added", "added"),
    ("deleted", "deleted"),
    ("geometry_changed", "geometry_changed"),
    ("class_changed", "class_changed"),
    ("modified_original", "modified_original"),
    ("unchanged", "unchanged"),
    ("transactions", "transactions"),
    ("touches", "touches"),
    ("unique_objects", "unique_objects"),
    ("working_seconds", "working_seconds"),
    ("completed", "completed"),
    ("quality", "quality"),
    ("issues", "issues"),
)

CLASS_TABLE_COLUMNS = (
    ("kind", "kind"),
    ("initial_class", "initial_class"),
    ("final_class", "final_class"),
    ("count", "count"),
    ("denominator", "denominator"),
    ("comparable", "comparable"),
    ("rounds", "rounds"),
    ("phase", "phase"),
    ("origin", "origin"),
    ("model", "model"),
    ("model_version", "model_version"),
    ("category_version", "category_version"),
)

GROUP_TABLE_COLUMNS = (
    ("density", "density"),
    ("rounds", "rounds"),
    ("images", "image_count"),
    ("final_count", "final_count"),
    ("baseline_count", "baseline_count"),
    ("modified_original", "modified_original"),
    ("modified_rate", "modified_rate"),
    ("working_seconds", "working_seconds"),
    ("median_seconds", "median_seconds"),
    ("seconds_per_100", "seconds_per_100"),
    ("model", "model"),
    ("model_version", "model_version"),
    ("category_version", "category_version"),
    ("phase", "phase"),
    ("origin", "origin"),
)

_SECONDS_KEYS = frozenset(
    {"working_seconds", "median_seconds", "seconds_per_100"}
)
_RATE_KEYS = frozenset({"modified_rate", "unchanged_rate"})
_IMAGE_NUMERIC = frozenset(key for key, _ in IMAGE_TABLE_COLUMNS) - {
    "image_path", "round_id", "phase", "origin", "quality", "issues",
}
_CLASS_NUMERIC = frozenset({"count", "denominator", "rounds"})
_GROUP_NUMERIC = frozenset(key for key, _ in GROUP_TABLE_COLUMNS) - {
    "density", "phase", "origin", "model", "model_version", "category_version",
}


def _catalog_messages():
    """Return the shared catalog mapping, or an empty one when unavailable."""
    try:
        from . import i18n

        return getattr(i18n, "MESSAGES", None) or {}
    except Exception:  # noqa: BLE001 - a broken catalog must not hide the report
        return {}


def _tr(key, language=None, **values):
    """Translate ``key``; prefer the shared catalog, then this module's table."""
    language = language or "en_US"
    if key in _catalog_messages():
        try:
            from . import i18n

            translated = i18n.tr(key, language, **values)
        except Exception:  # noqa: BLE001 - fall through to the local tables
            translated = None
        if translated and translated != key:
            return translated
    entry = _STRINGS.get(key)
    text = None
    if entry:
        text = entry.get(language) or entry.get("en_US")
    if text is None:
        text = _FALLBACK.get(key, key)
    if values:
        try:
            text = text.format(**values)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def known_key(key):
    """Whether ``key`` has a display string in any available catalog."""
    return (
        key in _STRINGS
        or key in _FALLBACK
        or key in _catalog_messages()
    )


class _ExportThread(QThread):
    """Run exactly one CSV export off the GUI thread.

    ``controller.export`` already publishes atomically, so the thread only
    forwards progress and one terminal state.  A cancellation request reaches
    ``export.py`` as the ``cancelled`` callable and is re-checked directly
    before the atomic rename.
    """

    progressed = pyqtSignal(int, int)
    succeeded = pyqtSignal(str)
    cancelled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, controller, kind, path, cancel_event, parent=None,
                 rows=None):
        super().__init__(parent)
        self.controller = controller
        self.kind = kind
        self.path = path
        self.cancel_event = cancel_event
        # Freeze the rows the dialog is currently showing so the CSV matches
        # the table exactly, even if the session keeps recording meanwhile.
        self.rows = tuple(rows or ())

    def run(self):  # noqa: D102 - QThread entry point
        try:
            result = self.controller.export(
                self.kind,
                self.path,
                cancelled=self.cancel_event.is_set,
                progress=self._report,
                rows=self.rows,
            )
        except export_module.ExportCancelled:
            self.cancelled.emit()
        except Exception as error:  # noqa: BLE001 - report, never crash the GUI
            self.failed.emit("%s: %s" % (type(error).__name__, error))
        else:
            if result is False:
                self.failed.emit("export returned False")
            else:
                self.succeeded.emit(self.path)

    def _report(self, done, total):
        self.progressed.emit(int(done), int(total))


class ReportDialog(QDialog):
    """Frozen, paged report with an atomic CSV export."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.language = str(getattr(controller, "language", None) or "en_US")
        self._rows = ()
        self._page = 0
        self._outcome = (0, 0, Counter())
        self._exclusion_counts = {}
        self._excluded_rows = 0
        self._reported_total = None
        self._class_sort = ("count", True)
        self._group_sort = ("final_count", True)
        self._class_records = ()
        self._group_records = ()
        self._cancel = threading.Event()
        self._thread = None
        self._last_directory = os.getcwd()

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------- strings
    def _text(self, key, **values):
        return _tr(key, self.language, **values)

    def _known_text(self, value):
        if value is None:
            return NA
        text = str(value)
        return self._text(text) if known_key(text) else text

    def _reason_text(self, code):
        key = _REASON_KEYS.get(str(code))
        if key is not None:
            return self._text(key)
        slug = str(code).replace("-", "_")
        if known_key(slug):
            return self._text(slug)
        return str(code)

    # ------------------------------------------------------------------ ui
    def _build_ui(self):
        self.setWindowTitle(self._text("report_title"))
        self.resize(1000, 640)
        self.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        self.refresh_button = QPushButton(self._text("refresh"), self)
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        self.snapshot_label = QLabel("", self)
        toolbar.addWidget(self.snapshot_label)
        toolbar.addStretch(1)
        self.export_button = QToolButton(self)
        self.export_button.setText(self._text("export"))
        self.export_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.export_menu = QMenu(self.export_button)
        self.export_images_action = self.export_menu.addAction(
            self._text("export_images")
        )
        self.export_images_action.triggered.connect(
            lambda: self._choose_export("images")
        )
        self.export_classes_action = self.export_menu.addAction(
            self._text("export_classes")
        )
        self.export_classes_action.triggered.connect(
            lambda: self._choose_export("classes")
        )
        self.export_dictionary_action = self.export_menu.addAction(
            self._text("export_dictionary")
        )
        self.export_dictionary_action.triggered.connect(
            lambda: self._choose_export("dictionary")
        )
        self.export_button.setMenu(self.export_menu)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)

        self.counts_label = QLabel("", self)
        self.counts_label.setWordWrap(True)
        self.stats_label = QLabel("", self)
        self.stats_label.setWordWrap(True)
        self.excluded_label = QLabel("", self)
        self.excluded_summary = QLabel("", self)
        self.excluded_summary.setWordWrap(True)
        self.details_button = QToolButton(self)
        self.details_button.setText(self._text("details"))
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        stats.setVerticalSpacing(2)
        self.excluded_header = QLabel(self._text("excluded"), self)
        stats.addWidget(self.counts_label, 0, 0, 1, 3)
        stats.addWidget(self.stats_label, 1, 0, 1, 2)
        stats.addWidget(self.excluded_label, 1, 2)
        stats.addWidget(self.excluded_header, 2, 0)
        stats.addWidget(self.excluded_summary, 2, 1)
        stats.addWidget(self.details_button, 2, 2)
        layout.addLayout(stats)

        self.exclusion_tree = QTreeWidget(self)
        self.exclusion_tree.setColumnCount(1)
        self.exclusion_tree.setHeaderLabels([self._text("excluded")])
        self.exclusion_tree.setRootIsDecorated(True)
        self.exclusion_tree.setVisible(False)
        self.exclusion_tree.setMaximumHeight(150)
        layout.addWidget(self.exclusion_tree)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_images_tab(), self._text("images"))
        self.tabs.addTab(self._build_classes_tab(), self._text("classes"))
        self.tabs.addTab(self._build_groups_tab(), self._text("groups"))
        layout.addWidget(self.tabs, 1)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar(self)
        self.progress.setVisible(False)
        self.progress.setFormat("%p%")
        progress_row.addWidget(self.progress, 1)
        self.cancel_button = QPushButton(self._text("cancel"), self)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_export)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)

        footer = QHBoxLayout()
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.close_button = QPushButton(self._text("close"), self)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)

    def _new_table(self, columns):
        table = QTableWidget(0, len(columns), self)
        table.setHorizontalHeaderLabels([self._text(key) for _, key in columns])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setSortingEnabled(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        table.setToolTip(self._text("sort_hint"))
        table.setMinimumHeight(90)
        return table

    def _build_images_tab(self):
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(4)
        self.image_table = self._new_table(IMAGE_TABLE_COLUMNS)
        box.addWidget(self.image_table, 1)
        pager = QHBoxLayout()
        self.prev_button = QPushButton(self._text("prev"), page)
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button = QPushButton(self._text("next"), page)
        self.next_button.clicked.connect(self.next_page)
        self.page_label = QLabel("", page)
        pager.addWidget(self.prev_button)
        pager.addWidget(self.page_label)
        pager.addStretch(1)
        pager.addWidget(self.next_button)
        box.addLayout(pager)
        return page

    def _build_classes_tab(self):
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(4)
        self.class_search = QLineEdit(page)
        self.class_search.setPlaceholderText(self._text("search"))
        self.class_search.setClearButtonEnabled(True)
        self.class_search.textChanged.connect(self._reload_classes)
        box.addWidget(self.class_search)
        self.class_table = self._new_table(CLASS_TABLE_COLUMNS)
        self.class_table.horizontalHeader().sectionClicked.connect(
            self._class_header_clicked
        )
        box.addWidget(self.class_table, 1)
        return page

    def _build_groups_tab(self):
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(4)
        self.group_search = QLineEdit(page)
        self.group_search.setPlaceholderText(self._text("search"))
        self.group_search.setClearButtonEnabled(True)
        self.group_search.textChanged.connect(self._reload_groups)
        box.addWidget(self.group_search)
        note = QLabel(self._text("group_note"), page)
        note.setWordWrap(True)
        box.addWidget(note)
        self.group_table = self._new_table(GROUP_TABLE_COLUMNS)
        self.group_table.horizontalHeader().sectionClicked.connect(
            self._group_header_clicked
        )
        box.addWidget(self.group_table, 1)
        return page

    # --------------------------------------------------------- public API
    def refresh(self):
        """Freeze a new snapshot from the controller and rebuild every view."""
        rows = self.controller.rows() if self.controller is not None else ()
        self._rows = tuple(rows or ())
        try:
            self._reported_total = int(self.controller.count())
        except Exception:  # noqa: BLE001 - count is informative only
            self._reported_total = None
        self._page = 0
        self.snapshot_label.setText(
            self._text(
                "snapshot",
                stamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        self._refresh_stats()
        self._render_page()
        self._reload_classes()
        self._reload_groups()
        if not self._rows:
            self._set_status(self._text("no_data"))
        return self._rows

    def export_images(self, path):
        """Export the frozen snapshot's image rounds to ``path`` (async)."""
        return self._start_export("images", path)

    def export_classes(self, path):
        """Export the frozen snapshot's class changes to ``path`` (async)."""
        return self._start_export("classes", path)

    def export_dictionary(self, path):
        """Export the metric dictionary to ``path`` (async)."""
        return self._start_export("dictionary", path)

    def cancel_export(self):
        """Ask a running export to stop; ``export.py`` publishes nothing then."""
        self._cancel.set()
        if self._thread is not None:
            self.cancel_button.setEnabled(False)
            return True
        return True

    def is_exporting(self):
        return self._thread is not None and self._thread.isRunning()

    def wait_for_export(self, timeout_ms=20000):
        """Process events until the export thread is idle (test helper)."""
        deadline = timeout_ms / 1000.0
        app = QApplication.instance()
        waited = 0.0
        while waited < deadline:
            thread = self._thread
            if thread is None:
                if app is not None:
                    app.processEvents(
                        QEventLoop.ProcessEventsFlag.AllEvents, 10
                    )
                return True
            thread.wait(10)
            waited += 0.01
            if app is not None:
                app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        return self._thread is None

    # ------------------------------------------------------------ snapshot
    @property
    def snapshot(self):
        return self._rows

    @property
    def total_rows(self):
        return len(self._rows)

    @property
    def reported_total(self):
        return self._reported_total

    @property
    def page_index(self):
        return self._page

    @property
    def page_count(self):
        if not self._rows:
            return 1
        return (len(self._rows) + PAGE_SIZE - 1) // PAGE_SIZE

    @property
    def exclusion_counts(self):
        return dict(self._exclusion_counts)

    @property
    def excluded_rows(self):
        return self._excluded_rows

    @property
    def outcome(self):
        return self._outcome

    def page_rows(self):
        start = self._page * PAGE_SIZE
        return self._rows[start:start + PAGE_SIZE]

    def go_to_page(self, index):
        index = max(0, min(int(index), self.page_count - 1))
        if index == self._page:
            return False
        self._page = index
        self._render_page()
        return True

    def next_page(self):
        return self.go_to_page(self._page + 1)

    def previous_page(self):
        return self.go_to_page(self._page - 1)

    # --------------------------------------------------------------- stats
    def _refresh_stats(self):
        rows = self._rows
        images_done, comparable, excluded_reasons = reporting.outcome(rows)
        self._outcome = (images_done, comparable, excluded_reasons)
        counts = Counter()
        excluded_rows = 0
        for row in rows:
            reasons = reporting.exclusion_reasons(row)
            if reasons:
                excluded_rows += 1
                counts.update(reasons)
        self._exclusion_counts = dict(counts)
        self._excluded_rows = excluded_rows

        self.counts_label.setText(
            self._text(
                "counts",
                images=images_done,
                eligible=comparable,
                rounds=len(rows),
            )
        )
        phases = Counter(str(row.get("phase") or "") for row in rows)
        distinct = len(
            {
                (
                    row.get("dataset_id"),
                    row.get("image_path"),
                    row.get("label_path"),
                )
                for row in rows
            }
        )
        self.stats_label.setText(
            "%s: %d \u00b7 %s"
            % (
                self._text("images_count"),
                distinct,
                self._text(
                    "rounds_phases",
                    rounds=len(rows),
                    correction=phases.get("correction", 0),
                    review=phases.get("review", 0),
                ),
            )
        )
        self.excluded_label.setText(
            self._text("excluded_total", count=excluded_rows)
        )
        if counts:
            self.excluded_summary.setText(
                " \u00b7 ".join(
                    "%s \u00d7%d" % (self._reason_text(reason), count)
                    for reason, count in sorted(
                        counts.items(), key=lambda item: (-item[1], item[0])
                    )
                )
            )
        else:
            self.excluded_summary.setText(self._text("excluded_none"))
        self.details_button.setEnabled(bool(counts))
        if not counts:
            self.details_button.setChecked(False)
        self.exclusion_tree.setVisible(
            bool(counts) and self.details_button.isChecked()
        )
        self._fill_exclusion_tree()

    def _fill_exclusion_tree(self):
        self.exclusion_tree.clear()
        if not self._exclusion_counts:
            return
        for reason, count in sorted(
            self._exclusion_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            parent = QTreeWidgetItem(
                ["%s \u00d7%d" % (self._reason_text(reason), count)]
            )
            self.exclusion_tree.addTopLevelItem(parent)
            shown = 0
            for row in self._rows:
                if reason not in reporting.exclusion_reasons(row):
                    continue
                if shown >= 50:
                    break
                parent.addChild(
                    QTreeWidgetItem(
                        [
                            "%s \u00b7 %s"
                            % (
                                row.get("image_path") or NA,
                                row.get("round_id") or NA,
                            )
                        ]
                    )
                )
                shown += 1

    def _toggle_details(self, checked):
        self.exclusion_tree.setVisible(
            bool(checked) and bool(self._exclusion_counts)
        )
        self.details_button.setText(
            self._text("hide_details") if checked else self._text("details")
        )

    # -------------------------------------------------------------- tables
    def _render_table(self, table, columns, records, cell, numeric):
        table.setUpdatesEnabled(False)
        try:
            table.clearContents()
            table.setRowCount(len(records))
            for row_index, record in enumerate(records):
                for column, (key, _) in enumerate(columns):
                    item = QTableWidgetItem(cell(record, key))
                    if key in numeric:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    table.setItem(row_index, column, item)
        finally:
            table.setUpdatesEnabled(True)

    @staticmethod
    def _format_value(value, *, seconds=False, rate=False):
        if value is None:
            return NA
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            if seconds:
                return "%.1f" % value
            if rate:
                return "%.3f" % value
            return ("%.2f" % value).rstrip("0").rstrip(".")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, (tuple, list)):
            return ", ".join(
                ReportDialog._format_value(item) for item in value
            )
        return str(value)

    def _render_page(self):
        rows = self.page_rows()
        self._render_table(
            self.image_table,
            IMAGE_TABLE_COLUMNS,
            rows,
            self._image_cell,
            _IMAGE_NUMERIC,
        )
        self.page_label.setText(
            self._text(
                "page",
                page=self._page + 1,
                pages=self.page_count,
                count=len(self._rows),
            )
        )
        self.prev_button.setEnabled(self._page > 0)
        self.next_button.setEnabled(self._page + 1 < self.page_count)

    def _image_cell(self, row, key):
        if key == "completed":
            return (
                self._text("yes") if row.get("completed") else self._text("no")
            )
        if key == "quality":
            quality = row.get("quality") or "not-assessed"
            return self._known_text(quality)
        if key == "phase":
            phase = row.get("phase")
            if phase == "review":
                return self._text("review_phase")
            return self._known_text(phase)
        if key == "issues":
            values = [
                self._reason_text(issue) for issue in row.get("issues") or ()
            ]
            return " \u00b7 ".join(values) if values else self._text("clean")
        if key == "origin":
            return self._known_text(row.get("origin"))
        if key == "working_seconds":
            return self._format_value(row.get(key), seconds=True)
        if key in ("image_path", "round_id"):
            value = row.get(key)
            return NA if value in (None, "") else str(value)
        return self._format_value(row.get(key))

    # ----------------------------------------------------- class direction
    def _reload_classes(self):
        sort_key, descending = self._class_sort
        _, records = reporting.view_records(
            self._rows,
            "class",
            self.class_search.text(),
            sort_key,
            descending,
        )
        self._class_records = tuple(records)
        self._render_table(
            self.class_table,
            CLASS_TABLE_COLUMNS,
            records,
            self._class_cell,
            _CLASS_NUMERIC,
        )
        self._show_sort_indicator(
            self.class_table, CLASS_TABLE_COLUMNS, sort_key, descending
        )

    def _class_cell(self, record, key):
        if key == "comparable":
            return (
                self._text("yes")
                if record.get("denominator") is not None
                else NA
            )
        if key == "kind":
            return self._known_text(record.get("kind"))
        if key == "phase":
            phase = record.get("phase")
            if phase == "review":
                return self._text("review_phase")
            return self._known_text(phase)
        if key == "origin":
            return self._known_text(record.get("origin"))
        return self._format_value(record.get(key))

    def _class_header_clicked(self, index):
        if 0 <= index < len(CLASS_TABLE_COLUMNS):
            self.apply_class_sort(CLASS_TABLE_COLUMNS[index][0])

    def apply_class_sort(self, key, descending=None):
        """Sort the class table with ``reporting.view_records`` ordering."""
        sort_key = "denominator" if key == "comparable" else key
        if sort_key not in reporting.CLASS_VIEW:
            return False
        current_key, current_descending = self._class_sort
        if descending is None:
            descending = sort_key == current_key and not current_descending
        self._class_sort = (sort_key, bool(descending))
        self._reload_classes()
        return True

    @property
    def class_records(self):
        return self._class_records

    # --------------------------------------------------------------- groups
    def _reload_groups(self):
        sort_key, descending = self._group_sort
        _, records = reporting.view_records(
            self._rows,
            "group",
            self.group_search.text(),
            sort_key,
            descending,
        )
        self._group_records = tuple(records)
        self._render_table(
            self.group_table,
            GROUP_TABLE_COLUMNS,
            records,
            self._group_cell,
            _GROUP_NUMERIC,
        )
        self._show_sort_indicator(
            self.group_table, GROUP_TABLE_COLUMNS, sort_key, descending
        )

    def _group_cell(self, record, key):
        if key == "phase":
            phase = record.get("phase")
            if phase == "review":
                return self._text("review_phase")
            return self._known_text(phase)
        if key == "origin":
            return self._known_text(record.get("origin"))
        if key in _SECONDS_KEYS:
            return self._format_value(record.get(key), seconds=True)
        if key in _RATE_KEYS:
            return self._format_value(record.get(key), rate=True)
        return self._format_value(record.get(key))

    def _group_header_clicked(self, index):
        if 0 <= index < len(GROUP_TABLE_COLUMNS):
            self.apply_group_sort(GROUP_TABLE_COLUMNS[index][0])

    def apply_group_sort(self, key, descending=None):
        """Sort the density/model table with ``reporting.view_records``."""
        if key not in reporting.GROUP_VIEW:
            return False
        current_key, current_descending = self._group_sort
        if descending is None:
            descending = key == current_key and not current_descending
        self._group_sort = (key, bool(descending))
        self._reload_groups()
        return True

    @property
    def group_records(self):
        return self._group_records

    @staticmethod
    def _show_sort_indicator(table, columns, sort_key, descending):
        keys = [key for key, _ in columns]
        if sort_key not in keys:
            return
        order = (
            Qt.SortOrder.DescendingOrder
            if descending
            else Qt.SortOrder.AscendingOrder
        )
        header = table.horizontalHeader()
        header.setSortIndicator(keys.index(sort_key), order)
        header.setSortIndicatorShown(True)

    # --------------------------------------------------------------- export
    def _default_export_path(self, kind):
        names = {
            "images": "correction-images.csv",
            "classes": "correction-classes.csv",
            "dictionary": "correction-dictionary.csv",
        }
        return str(
            Path(self._last_directory) / names.get(kind, "correction.csv")
        )

    def _choose_export(self, kind):
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._text("export"),
            self._default_export_path(kind),
            "CSV (*.csv)",
        )
        if path:
            self._start_export(kind, path)

    def _set_status(self, text):
        self.status_label.setText(text)

    def _set_export_enabled(self, enabled):
        self.export_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)

    def _start_export(self, kind, path):
        if self._thread is not None:
            self._set_status(self._text("export_busy"))
            return False
        if not path:
            self._set_status(self._text("error"))
            return False
        destination = Path(os.fspath(path))
        if not destination.parent.is_dir():
            self._set_status(
                self._text("export_failed", error=str(destination.parent))
            )
            return False
        self._cancel.clear()
        thread = _ExportThread(
            self.controller, kind, str(destination), self._cancel, self,
            rows=self._rows,
        )
        thread.progressed.connect(self._on_export_progress)
        thread.succeeded.connect(self._on_export_succeeded)
        thread.cancelled.connect(self._on_export_cancelled)
        thread.failed.connect(self._on_export_failed)
        thread.finished.connect(self._on_export_finished)
        self._thread = thread
        self._last_directory = str(destination.parent)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self._set_export_enabled(False)
        self._set_status(self._text("exporting"))
        thread.start()
        return True

    def _on_export_progress(self, done, total):
        if total and total > 0:
            self.progress.setRange(0, int(total))
            self.progress.setValue(min(int(done), int(total)))

    def _on_export_succeeded(self, path):
        self._set_status(
            self._text("exported", file=os.path.basename(os.fspath(path)))
        )

    def _on_export_cancelled(self):
        self._set_status(self._text("export_cancelled"))

    def _on_export_failed(self, message):
        self._set_status(self._text("export_failed", error=message))

    def _on_export_finished(self):
        self._thread = None
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        self._set_export_enabled(True)

    def _stop_export(self, timeout_ms=5000):
        self._cancel.set()
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.wait(timeout_ms)
        return thread is None or not thread.isRunning()

    def closeEvent(self, event):  # noqa: N802 - Qt override
        self._stop_export()
        super().closeEvent(event)

    def done(self, result):  # noqa: N802 - Qt override
        self._stop_export()
        super().done(result)
