"""Offscreen Qt tests for the correction-cost report dialog.

The repository-wide ``tests/conftest.py`` sets ``QT_QPA_PLATFORM=offscreen``
and provides a session ``QApplication``.  Every case drives ``ReportDialog``
through a fake controller that implements only the documented surface:
``rows(limit=None, offset=0)``, ``count()`` and
``export(kind, path, cancelled=None, progress=None)``.

The fake export deliberately delegates to the real
``services/correction_metrics/export.py`` so cancellation is exercised against
the production atomic-publish path instead of a mock that cannot prove it.
"""

from __future__ import annotations

import csv
import io
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from anylabeling.services.correction_metrics import export as export_module
from anylabeling.services.correction_metrics import reporting
from anylabeling.views.labeling.correction_metrics.report_dialog import (
    CLASS_TABLE_COLUMNS,
    GROUP_TABLE_COLUMNS,
    IMAGE_TABLE_COLUMNS,
    NA,
    PAGE_SIZE,
    ReportDialog,
)


def _column(columns, key):
    return [name for name, _ in columns].index(key)


def _cell(dialog, table, row, columns, key):
    return table.item(row, _column(columns, key)).text()


def make_raw_row(index, **overrides):
    """One stored round in the shape ``reporting.saved_row`` consumes."""
    raw = {
        "schema_version": 3,
        "dataset_id": "dataset",
        "image_path": "/data/img-%03d.png" % index,
        "label_path": "/data/img-%03d.json" % index,
        "image_digest": "digest-%03d" % index,
        "round_id": "round-%03d" % index,
        "session_ids": ("session",),
        "phase": "correction",
        "origin": "replacement",
        "run_id": "run-001",
        "model": "yolov8",
        "model_version": "8.0",
        "config_digest": "config",
        "prompt": "boxes",
        "thresholds": {"score": 0.3},
        "category_version": "v1",
        "revision": "revision-%03d" % index,
        "current": True,
        "completed": True,
        "quality": "not-assessed",
        "comparable": True,
        "issues": (),
        "baseline_count": 10,
        "ai_count": 10,
        "final_count": 9,
        "unsupported_count": 0,
        "added": 1,
        "deleted": 2,
        "geometry_changed": 1,
        "class_changed": 1,
        "modified_original": 4,
        "unchanged": 6,
        "modified_rate": 0.4,
        "unchanged_rate": 0.6,
        "transactions": 3,
        "touches": 5,
        "unique_objects": 4,
        "undo_count": 0,
        "operation_counts": {"move": 2},
        "time": {"working": 12.5, "adjusted_working": 10.0},
        "inference_seconds": 1.5,
        "classes": (),
    }
    raw.update(overrides)
    return raw


def make_row(index, **overrides):
    return reporting.saved_row(make_raw_row(index, **overrides))


class FakeController:
    """Documented controller surface plus a real atomic export."""

    language = "en_US"

    def __init__(self, rows=(), *, fail=False, gate=None, cancel_after=None):
        self._rows = list(rows)
        self.export_kinds = []
        self.export_rows = None
        self.fail = fail
        self.gate = gate
        self.cancel_after = cancel_after
        self.entered = threading.Event()

    def add_row(self, row):
        self._rows.append(row)

    def rows(self, limit=None, offset=0):
        if limit is None:
            return list(self._rows)
        return list(self._rows[offset:offset + limit])

    def count(self):
        return len(self._rows)

    def export(self, kind, path, cancelled=None, progress=None, rows=None):
        self.export_kinds.append(kind)
        self.export_rows = None if rows is None else list(rows)
        self.entered.set()
        if self.gate is not None and not self.gate.wait(5.0):
            raise AssertionError("gate was never released")
        if self.fail:
            raise RuntimeError("synthetic export failure")
        # The dialog freezes the rows it shows; fall back to the live list.
        rows = list(self._rows if rows is None else rows)
        written = {"rows": 0}

        def cancelled_now():
            if cancelled is not None and cancelled():
                return True
            return (
                self.cancel_after is not None
                and written["rows"] >= self.cancel_after
            )

        def report(done, total):
            written["rows"] = done
            if progress is not None:
                progress(done, total)

        return export_module.export_csv(
            path, rows, kind, cancelled=cancelled_now, progress=report
        )


def _dialog(rows, **kwargs):
    return ReportDialog(FakeController(rows, **kwargs))


def test_pagination_freezes_snapshot_and_slices_pages():
    rows = [make_row(index) for index in range(120)]
    controller = FakeController(rows)
    dialog = ReportDialog(controller)
    try:
        assert dialog.total_rows == 120
        assert dialog.reported_total == 120
        assert dialog.page_count == 3
        assert dialog.page_index == 0
        assert dialog.page_rows() == tuple(rows[:PAGE_SIZE])
        assert dialog.image_table.rowCount() == PAGE_SIZE

        label = dialog.page_label.text()
        assert "1/3" in label
        assert "120" in label
        assert dialog.prev_button.isEnabled() is False
        assert dialog.next_button.isEnabled() is True

        assert dialog.next_page() is True
        assert dialog.page_index == 1
        assert dialog.image_table.rowCount() == PAGE_SIZE
        assert (
            _cell(
                dialog,
                dialog.image_table,
                0,
                IMAGE_TABLE_COLUMNS,
                "image_path",
            )
            == rows[PAGE_SIZE]["image_path"]
        )

        assert dialog.next_page() is True
        assert dialog.image_table.rowCount() == 120 - 2 * PAGE_SIZE
        assert dialog.next_button.isEnabled() is False
        assert dialog.previous_page() is True
        assert dialog.page_index == 1

        # frozen snapshot: a later edit is invisible until the next refresh
        controller.add_row(make_row(500))
        assert dialog.total_rows == 120
        assert "120" in dialog.page_label.text()
        dialog.refresh()
        assert dialog.total_rows == 121
        assert dialog.page_count == 3
    finally:
        dialog.close()


def test_exclusion_reasons_are_aggregated_with_expandable_detail():
    rows = [
        make_row(0, revision=None),                      # unsaved
        make_row(1, completed=False),                    # unfinished
        make_row(2, comparable=False),                   # incomplete
        make_row(3, comparable=False, issues=("storage-gap",)),
        make_row(4),                                     # comparable
    ]
    dialog = _dialog(rows)
    try:
        assert dialog.exclusion_counts == {
            "unsaved": 1,
            "unfinished": 2,
            "incomplete": 2,
            "storage-gap": 1,
        }
        assert dialog.excluded_rows == 4
        assert "4" in dialog.excluded_label.text()
        summary = dialog.excluded_summary.text()
        assert "\u00d7" in summary
        assert "Storage gap" in summary or "storage" in summary.casefold()

        # the per-row reasons agree with the reporting projection
        expected = {}
        for row in rows:
            for reason in reporting.exclusion_reasons(row):
                expected[reason] = expected.get(reason, 0) + 1
        assert dialog.exclusion_counts == expected

        assert dialog.exclusion_tree.isHidden() is True
        dialog.details_button.setChecked(True)
        assert dialog.exclusion_tree.isHidden() is False
        assert dialog.exclusion_tree.topLevelItemCount() == len(expected)
        parents = [
            dialog.exclusion_tree.topLevelItem(index).text(0)
            for index in range(dialog.exclusion_tree.topLevelItemCount())
        ]
        assert any("\u00d72" in text for text in parents)
        children = dialog.exclusion_tree.topLevelItem(0).childCount()
        assert children >= 1

        images_done, comparable, _ = dialog.outcome
        assert images_done == 3
        assert comparable == 1
    finally:
        dialog.close()


def test_none_renders_as_na_and_zero_stays_zero():
    rows = [
        make_row(0, revision=None),
        make_row(1, added=0, unchanged=0, ai_count=0, working_seconds=None),
    ]
    dialog = _dialog(rows)
    try:
        table = dialog.image_table
        assert (
            _cell(dialog, table, 0, IMAGE_TABLE_COLUMNS, "unchanged") == NA
        )
        assert _cell(dialog, table, 0, IMAGE_TABLE_COLUMNS, "added") == NA
        assert _cell(dialog, table, 0, IMAGE_TABLE_COLUMNS, "completed") == (
            dialog._text("no")
        )
        assert _cell(dialog, table, 1, IMAGE_TABLE_COLUMNS, "unchanged") == "0"
        assert _cell(dialog, table, 1, IMAGE_TABLE_COLUMNS, "added") == "0"
        assert NA != "0"
        # default quality stays not-assessed instead of being guessed
        assert (
            _cell(dialog, table, 1, IMAGE_TABLE_COLUMNS, "quality")
            == dialog._text("not-assessed")
        )
        assert (
            _cell(dialog, table, 1, IMAGE_TABLE_COLUMNS, "issues")
            == dialog._text("clean")
        )
    finally:
        dialog.close()


def test_class_direction_table_matches_class_details_groups():
    changes = (
        {
            "kind": "added",
            "initial_class": None,
            "final_class": "cat",
            "count": 2,
            "denominator": None,
        },
        {
            "kind": "class_changed",
            "initial_class": "cat",
            "final_class": "dog",
            "count": 3,
            "denominator": 10,
        },
    )
    rows = [make_row(0, classes=changes), make_row(1, classes=changes)]
    expected = reporting.class_groups(rows)
    dialog = _dialog(rows)
    try:
        assert len(expected) == 2
        assert dialog.class_table.rowCount() == len(expected)
        assert len(dialog.class_records) == len(expected)

        directions = {
            (
                _cell(dialog, dialog.class_table, row, CLASS_TABLE_COLUMNS,
                      "initial_class"),
                _cell(dialog, dialog.class_table, row, CLASS_TABLE_COLUMNS,
                      "final_class"),
            )
            for row in range(dialog.class_table.rowCount())
        }
        assert (NA, "cat") in directions
        assert ("cat", "dog") in directions

        dog_row = next(
            row
            for row in range(dialog.class_table.rowCount())
            if _cell(dialog, dialog.class_table, row, CLASS_TABLE_COLUMNS,
                     "final_class") == "dog"
        )
        assert _cell(dialog, dialog.class_table, dog_row,
                     CLASS_TABLE_COLUMNS, "count") == "6"
        assert _cell(dialog, dialog.class_table, dog_row,
                     CLASS_TABLE_COLUMNS, "denominator") == "20"
        assert _cell(dialog, dialog.class_table, dog_row,
                     CLASS_TABLE_COLUMNS, "rounds") == "2"
        assert _cell(dialog, dialog.class_table, dog_row,
                     CLASS_TABLE_COLUMNS, "comparable") == dialog._text("yes")

        added_row = next(
            row
            for row in range(dialog.class_table.rowCount())
            if _cell(dialog, dialog.class_table, row, CLASS_TABLE_COLUMNS,
                     "initial_class") == NA
        )
        assert _cell(dialog, dialog.class_table, added_row,
                     CLASS_TABLE_COLUMNS, "count") == "4"
        assert _cell(dialog, dialog.class_table, added_row,
                     CLASS_TABLE_COLUMNS, "denominator") == NA
        assert _cell(dialog, dialog.class_table, added_row,
                     CLASS_TABLE_COLUMNS, "comparable") == NA

        # searchable through reporting.view_records
        dialog.class_search.setText("dog")
        assert dialog.class_table.rowCount() == 1
        assert _cell(dialog, dialog.class_table, 0, CLASS_TABLE_COLUMNS,
                     "final_class") == "dog"
        dialog.class_search.setText("")
        assert dialog.class_table.rowCount() == len(expected)

        # sortable through reporting.view_records ordering
        assert dialog.apply_class_sort("count", descending=True) is True
        descending = [
            int(_cell(dialog, dialog.class_table, row, CLASS_TABLE_COLUMNS,
                      "count"))
            for row in range(dialog.class_table.rowCount())
        ]
        assert descending == sorted(descending, reverse=True)
        assert dialog.apply_class_sort("count", descending=False) is True
        ascending = [
            int(_cell(dialog, dialog.class_table, row, CLASS_TABLE_COLUMNS,
                      "count"))
            for row in range(dialog.class_table.rowCount())
        ]
        assert ascending == sorted(ascending)
        assert dialog.apply_class_sort("not-a-column") is False
    finally:
        dialog.close()


def test_density_groups_include_zero_target_group_and_na_rate():
    rows = [
        make_row(0, final_count=0, baseline_count=0, added=0, deleted=0,
                 geometry_changed=0, class_changed=0,
                 modified_original=0, unchanged=0, modified_rate=0.0,
                 unchanged_rate=None),
        make_row(1, final_count=25, baseline_count=25),
    ]
    expected = reporting.density_groups(rows)
    dialog = _dialog(rows)
    try:
        assert len(expected) == len({record["density"] for record in expected})
        assert dialog.group_table.rowCount() == len(expected)

        densities = {
            _cell(dialog, dialog.group_table, row, GROUP_TABLE_COLUMNS,
                  "density")
            for row in range(dialog.group_table.rowCount())
        }
        assert "0" in densities
        assert "11\u201330" in densities

        zero_row = next(
            row
            for row in range(dialog.group_table.rowCount())
            if _cell(dialog, dialog.group_table, row, GROUP_TABLE_COLUMNS,
                     "density") == "0"
        )
        rate = _cell(dialog, dialog.group_table, zero_row,
                     GROUP_TABLE_COLUMNS, "seconds_per_100")
        assert rate == NA
        assert rate != "0"

        dense_row = next(
            row
            for row in range(dialog.group_table.rowCount())
            if _cell(dialog, dialog.group_table, row, GROUP_TABLE_COLUMNS,
                     "density") == "11\u201330"
        )
        assert _cell(dialog, dialog.group_table, dense_row,
                     GROUP_TABLE_COLUMNS, "seconds_per_100") == "40.0"
        assert _cell(dialog, dialog.group_table, dense_row,
                     GROUP_TABLE_COLUMNS, "images") == "1"
        rate_item = dialog.group_table.item(
            dense_row, _column(GROUP_TABLE_COLUMNS, "seconds_per_100")
        )
        assert rate_item.textAlignment() & int(Qt.AlignmentFlag.AlignRight)
    finally:
        dialog.close()


def test_export_images_writes_bom_csv_and_cleans_temporary_file(tmp_path):
    rows = [make_row(index) for index in range(3)]
    controller = FakeController(rows)
    dialog = ReportDialog(controller)
    target = tmp_path / "rounds.csv"
    try:
        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        assert controller.export_kinds == ["images"]
        assert target.exists()
        raw = target.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        parsed = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        assert parsed[0] == list(export_module.CSV_COLUMNS["images"])
        assert len(parsed) == 1 + len(rows)
        assert dialog.status_label.text() == dialog._text(
            "exported", file="rounds.csv"
        )
        assert list(tmp_path.glob(".correction-export-*")) == []
        assert dialog.export_button.isEnabled() is True
    finally:
        dialog.close()


def test_export_classes_and_dictionary_use_their_own_columns(tmp_path):
    change = {
        "kind": "class_changed",
        "initial_class": "cat",
        "final_class": "dog",
        "count": 1,
        "denominator": 5,
    }
    rows = [make_row(index, classes=(change,)) for index in range(2)]
    dialog = _dialog(rows)
    classes_target = tmp_path / "classes.csv"
    dictionary_target = tmp_path / "dictionary.csv"
    try:
        assert dialog.export_classes(classes_target) is True
        assert dialog.wait_for_export(20000) is True
        assert classes_target.exists()
        parsed = list(
            csv.reader(
                io.StringIO(classes_target.read_bytes().decode("utf-8-sig"))
            )
        )
        assert parsed[0] == list(export_module.CSV_COLUMNS["classes"])
        assert len(parsed) == 1 + len(rows)
        assert "cat" in parsed[1]

        assert dialog.export_dictionary(dictionary_target) is True
        assert dialog.wait_for_export(20000) is True
        assert dictionary_target.exists()
        dictionary = list(
            csv.reader(
                io.StringIO(
                    dictionary_target.read_bytes().decode("utf-8-sig")
                )
            )
        )
        assert dictionary[0] == list(export_module.CSV_COLUMNS["dictionary"])
        assert len(dictionary) == 1 + len(export_module.DEFINITIONS) + 3
        assert any(row[0] == "N/A" for row in dictionary[1:])
    finally:
        dialog.close()


def test_cancelled_export_leaves_no_target_file(tmp_path):
    rows = [make_row(index) for index in range(300)]
    dialog = _dialog(rows, cancel_after=128)
    target = tmp_path / "cancelled.csv"
    try:
        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        assert target.exists() is False
        assert list(tmp_path.glob(".correction-export-*")) == []
        assert dialog.status_label.text() == dialog._text("export_cancelled")
    finally:
        dialog.close()


def test_cancelled_export_keeps_the_previous_file(tmp_path):
    target = tmp_path / "existing.csv"
    target.write_text("previous contents", encoding="utf-8")
    dialog = _dialog(
        [make_row(index) for index in range(300)], cancel_after=128
    )
    try:
        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        assert target.read_text(encoding="utf-8") == "previous contents"
        assert list(tmp_path.glob(".correction-export-*")) == []
    finally:
        dialog.close()


def test_cancel_button_cancels_the_running_thread(tmp_path):
    gate = threading.Event()
    controller = FakeController(
        [make_row(index) for index in range(4)], gate=gate
    )
    dialog = ReportDialog(controller)
    target = tmp_path / "gated.csv"
    try:
        assert dialog.export_images(target) is True
        assert controller.entered.wait(5.0) is True
        assert dialog.is_exporting() is True
        assert dialog.cancel_button.isHidden() is False
        assert dialog.cancel_export() is True
        gate.set()
        assert dialog.wait_for_export(20000) is True
        assert dialog.is_exporting() is False
        assert target.exists() is False
        assert list(tmp_path.glob(".correction-export-*")) == []
    finally:
        gate.set()
        dialog.close()


def test_close_cancels_a_running_export_and_writes_nothing(tmp_path):
    gate = threading.Event()
    controller = FakeController([make_row(0)], gate=gate)
    dialog = ReportDialog(controller)
    target = tmp_path / "closing.csv"
    assert dialog.export_images(target) is True
    assert controller.entered.wait(5.0) is True
    gate.set()
    dialog.close()
    assert dialog.is_exporting() is False
    assert target.exists() is False
    assert list(tmp_path.glob(".correction-export-*")) == []


def test_export_failure_reports_and_leaves_no_file(tmp_path):
    dialog = _dialog([make_row(0)], fail=True)
    target = tmp_path / "failing.csv"
    try:
        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        assert target.exists() is False
        assert "synthetic export failure" in dialog.status_label.text()
        assert dialog.progress.isHidden() is True
    finally:
        dialog.close()


def test_no_exclusions_disables_the_detail_toggle():
    dialog = _dialog([make_row(0)])
    try:
        assert dialog.exclusion_counts == {}
        assert dialog.excluded_summary.text() == dialog._text("excluded_none")
        assert dialog.exclusion_tree.isHidden() is True
        assert dialog.details_button.isEnabled() is False
    finally:
        dialog.close()


def test_real_store_round_is_reported_and_exported(tmp_path):
    """Drive the dialog with a real MetricsStore round and a real export thread."""
    from anylabeling.services.correction_metrics.storage import MetricsStore
    from anylabeling.views.labeling.correction_metrics.controller import (
        CorrectionMetricsController,
    )

    from . import synthetic

    image = str(tmp_path / "images" / "scene.png")
    label = str(tmp_path / "labels" / "scene.json")
    controller = CorrectionMetricsController(
        None, language="en_US", storage_root=tmp_path / "metrics"
    )
    assert controller.start_scope(str(tmp_path / "images"),
                                  str(tmp_path / "labels")) is True
    store = controller._store
    assert isinstance(store, MetricsStore)
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    shape = synthetic.by_id(baseline)["o-001"]
    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    assert round_obj.saved(token) is True
    assert round_obj.finish() is True
    assert store.flush() is True

    dialog = ReportDialog(controller)
    target = tmp_path / "real.csv"
    try:
        assert dialog.total_rows == 1
        assert dialog.reported_total == 1
        assert dialog.page_count == 1
        stored_image = _cell(dialog, dialog.image_table, 0,
                             IMAGE_TABLE_COLUMNS, "image_path")
        # the store normalises paths (Windows case folding), compare safely
        assert stored_image.casefold() == image.casefold()
        assert _cell(dialog, dialog.image_table, 0, IMAGE_TABLE_COLUMNS,
                     "geometry_changed") == "1"
        assert _cell(dialog, dialog.image_table, 0, IMAGE_TABLE_COLUMNS,
                     "unchanged") == "11"
        assert _cell(dialog, dialog.image_table, 0, IMAGE_TABLE_COLUMNS,
                     "completed") == dialog._text("yes")
        images_done, comparable, _ = dialog.outcome
        assert images_done == 1
        assert comparable == 1
        assert dialog.exclusion_counts == {}
        assert dialog.group_table.rowCount() == 1

        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        assert target.exists()
        parsed = list(
            csv.reader(io.StringIO(target.read_bytes().decode("utf-8-sig")))
        )
        assert parsed[0] == list(export_module.CSV_COLUMNS["images"])
        assert len(parsed) == 2
        exported_image = parsed[1][parsed[0].index("image_path")]
        assert exported_image.casefold() == image.casefold()
    finally:
        dialog.close()
        controller.stop()
        store.close()


def test_export_uses_the_frozen_snapshot_not_later_rows(tmp_path):
    """The CSV must match the table on screen, even if the session continues."""
    controller = FakeController([make_row(index) for index in range(3)])
    dialog = ReportDialog(controller)
    target = tmp_path / "frozen.csv"
    try:
        controller.add_row(make_row(99))  # new round recorded after the refresh
        assert dialog.total_rows == 3
        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        parsed = list(
            csv.reader(io.StringIO(target.read_bytes().decode("utf-8-sig")))
        )
        assert len(parsed) == 1 + 3
        assert controller.export_rows is not None
        assert len(controller.export_rows) == 3
    finally:
        dialog.close()


def test_narrow_window_keeps_paging_and_export_reachable():
    app = QApplication.instance() or QApplication([])
    dialog = _dialog([make_row(index) for index in range(60)])
    try:
        dialog.resize(800, 600)
        dialog.show()
        app.processEvents()
        assert dialog.page_index == 0
        assert dialog.image_table.isVisible()
        assert dialog.image_table.height() > 60
        assert dialog.page_label.isVisible()
        assert dialog.prev_button.isVisible()
        assert dialog.next_button.isVisible()
        assert dialog.export_button.isVisible()
        assert dialog.tabs.isVisible()
        assert dialog.export_button.geometry().right() <= dialog.width()
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            app.processEvents()
            assert dialog.tabs.widget(index).isVisible()
    finally:
        dialog.close()
