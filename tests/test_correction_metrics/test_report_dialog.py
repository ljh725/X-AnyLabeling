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

    def __init__(self, rows=(), *, fail=False, gate=None, cancel_after=None,
                 complete_report=None):
        self._rows = list(rows)
        self.export_kinds = []
        self.export_rows = None
        self.fail = fail
        self.gate = gate
        self.cancel_after = cancel_after
        self.entered = threading.Event()
        self.rows_calls = 0
        self.complete_calls = []
        self.complete_report = complete_report or {
            "completed": [],
            "skipped": [],
        }

    def add_row(self, row):
        self._rows.append(row)

    def rows(self, limit=None, offset=0):
        self.rows_calls += 1
        if limit is None:
            return list(self._rows)
        return list(self._rows[offset:offset + limit])

    def count(self):
        return len(self._rows)

    def complete_scope(self, limit=None):
        self.complete_calls.append(limit)
        return {
            "completed": list(self.complete_report.get("completed") or ()),
            "skipped": [dict(item) for item
                        in self.complete_report.get("skipped") or ()],
        }

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


# ---------------------------------------------------------------------------
# 7.3 / 7.4 / 5.3 -- scope, model version, completion entry point
# ---------------------------------------------------------------------------
def test_scope_switch_filters_only_the_frozen_snapshot():
    rows = [
        make_row(0),                                # current + completed
        make_row(1, current=False),                 # historical
        make_row(2, completed=False),               # current, unfinished
        make_row(3, current=False, completed=False),
    ]
    controller = FakeController(rows)
    dialog = ReportDialog(controller)
    try:
        assert dialog.total_rows == 4  # default shows every round
        reads = controller.rows_calls

        dialog.set_filters(scope="current")
        assert dialog.total_rows == 1
        assert [row["image_path"] for row in dialog.snapshot] == [
            rows[0]["image_path"]
        ]
        assert controller.rows_calls == reads  # filtering never re-reads the DB

        dialog.set_filters(scope="history")
        assert dialog.total_rows == 2
        assert all(row["current"] is False for row in dialog.snapshot)

        dialog.set_filters(scope="all")
        assert dialog.total_rows == 4
        assert controller.rows_calls == reads
    finally:
        dialog.close()


def test_version_dropdown_lists_versions_and_filters_rows():
    rows = [
        make_row(0, model_version="v1"),
        make_row(1, model_version="v2"),
        make_row(2, model_version="v1"),
        make_row(3, model_version=None),
    ]
    controller = FakeController(rows)
    dialog = ReportDialog(controller)
    try:
        versions = [
            dialog.version_combo.itemData(index)
            for index in range(dialog.version_combo.count())
        ]
        assert versions[0] == ""
        assert set(versions[1:]) == {"v1", "v2"}

        dialog.set_filters(scope="all", version="v1")
        assert dialog.total_rows == 2
        assert all(row["model_version"] == "v1" for row in dialog.snapshot)

        dialog.set_filters(version="v2")
        assert [row["model_version"] for row in dialog.snapshot] == ["v2"]

        dialog.set_filters(version="")
        assert dialog.total_rows == 4
    finally:
        dialog.close()


def test_exclusion_counts_follow_the_selected_scope():
    rows = [
        make_row(0),
        make_row(1, completed=False),
        make_row(2, current=False),
    ]
    dialog = _dialog(rows)
    try:
        assert dialog.exclusion_counts == {"unfinished": 1}
        assert dialog.excluded_rows == 1

        dialog.set_filters(scope="current")
        assert dialog.exclusion_counts == {}
        assert dialog.excluded_rows == 0
        assert dialog.excluded_summary.text() == dialog._text("excluded_none")

        dialog.set_filters(scope="history")
        assert dialog.exclusion_counts == {}
        assert dialog.total_rows == 1
    finally:
        dialog.close()


def test_complete_button_calls_controller_reports_and_refreshes():
    report = {
        "completed": ["/data/img-000.png"],
        "skipped": [
            {"path": "/data/img-001.png", "reason": "unsaved"},
            {"path": "/data/img-002.png", "reason": "not-ready"},
        ],
    }
    controller = FakeController(
        [make_row(0), make_row(1), make_row(2)], complete_report=report
    )
    dialog = ReportDialog(controller)
    try:
        reads = controller.rows_calls
        result = dialog.complete_available_rounds()
        assert controller.rows_calls == reads + 1  # refreshed after completing
        assert controller.complete_calls == [None]
        assert result["completed"] == report["completed"]
        assert len(result["skipped"]) == 2
        text = dialog.complete_result.text()
        expected = dialog._text(
            "complete_result", completed=1, skipped=2
        )
        assert expected in text
        assert dialog.complete_result.isHidden() is False
        assert dialog.isModal() is False  # non-modal result, not a dialog box
        assert "unsaved" in text.casefold()
    finally:
        dialog.close()


def test_skipped_reasons_are_counted_without_faking_completion():
    report = {
        "completed": [],
        "skipped": [
            {"path": "/a.png", "reason": "unsaved-draft"},
            {"path": "/b.png", "reason": "unsaved-draft"},
            {"path": "/c.png", "reason": "unavailable"},
        ],
    }
    controller = FakeController([make_row(0)], complete_report=report)
    dialog = ReportDialog(controller)
    try:
        result = dialog.complete_available_rounds()
        assert result["completed"] == []
        text = dialog.complete_result.text()
        assert dialog._text(
            "complete_result", completed=0, skipped=3
        ) in text
        assert dialog._text("reason_unsaved_draft") in text
        assert "\u00d72" in text  # counted twice, not silently dropped
        # the dialog never marks a row completed on its own
        assert all(row.get("completed") for row in dialog.snapshot)
    finally:
        dialog.close()


def test_csv_export_uses_the_filtered_frozen_snapshot(tmp_path):
    rows = [
        make_row(0, model_version="v1"),
        make_row(1, model_version="v2"),
        make_row(2, model_version="v1"),
    ]
    controller = FakeController(rows)
    dialog = ReportDialog(controller)
    target = tmp_path / "filtered.csv"
    try:
        dialog.set_filters(scope="all", version="v1")
        assert dialog.total_rows == 2
        assert dialog.export_images(target) is True
        assert dialog.wait_for_export(20000) is True
        parsed = list(
            csv.reader(io.StringIO(target.read_bytes().decode("utf-8-sig")))
        )
        assert len(parsed) == 1 + 2
        exported = [row[parsed[0].index("image_path")] for row in parsed[1:]]
        assert len(exported) == dialog.total_rows
        assert all(
            path.casefold() in {row["image_path"].casefold()
                                for row in dialog.snapshot}
            for path in exported
        )
        assert controller.export_rows is not None
        assert len(controller.export_rows) == 2
    finally:
        dialog.close()


def test_tables_expose_no_accuracy_or_per_class_time_columns():
    forbidden = ("accuracy", "precision", "recall", "speedup", "per_class")
    for columns in (IMAGE_TABLE_COLUMNS, CLASS_TABLE_COLUMNS,
                    GROUP_TABLE_COLUMNS):
        for key, header in columns:
            for word in forbidden:
                assert word not in key.casefold()
                assert word not in header.casefold()

    dialog = _dialog([make_row(0)])
    try:
        for table_name in ("image_table", "class_table", "group_table"):
            table = getattr(dialog, table_name)
            headers = [
                table.horizontalHeaderItem(index).text().casefold()
                for index in range(table.columnCount())
            ]
            assert headers
            for word in forbidden:
                assert not any(word in header for header in headers)
    finally:
        dialog.close()


def test_class_sample_and_density_range_are_disclosed():
    change = {
        "kind": "class_changed",
        "initial_class": "cat",
        "final_class": "dog",
        "count": 3,
        "denominator": 10,
    }
    rows = [
        make_row(0, classes=(change,), final_count=0, baseline_count=0),
        make_row(1, classes=(change,), final_count=25, baseline_count=25),
    ]
    dialog = _dialog(rows)
    try:
        assert dialog.class_note.text() == dialog._text("class_note")
        assert dialog.model_version_note.text() == dialog._text(
            "model_version_note"
        )
        assert "denominator" in [key for key, _ in CLASS_TABLE_COLUMNS]
        assert "rounds" in [key for key, _ in CLASS_TABLE_COLUMNS]

        range_index = _column(GROUP_TABLE_COLUMNS, "range")
        zero_row = next(
            row
            for row in range(dialog.group_table.rowCount())
            if _cell(dialog, dialog.group_table, row,
                     GROUP_TABLE_COLUMNS, "density") == "0"
        )
        assert dialog.group_table.item(zero_row, range_index).text() == "0\u20130"
        assert _cell(dialog, dialog.group_table, zero_row,
                     GROUP_TABLE_COLUMNS, "seconds_per_100") == NA
        wide_row = next(
            row
            for row in range(dialog.group_table.rowCount())
            if _cell(dialog, dialog.group_table, row,
                     GROUP_TABLE_COLUMNS, "density") == "11\u201330"
        )
        assert dialog.group_table.item(wide_row, range_index).text() == "25\u201325"
        assert dialog.group_table.item(wide_row, 1).text() == "1"  # rounds sample
    finally:
        dialog.close()


# ---------------------------------------------------------------------------
# Task 6.5 -- model runtime and blocking wait stay separate columns
# ---------------------------------------------------------------------------
def test_the_report_lists_model_runtime_and_blocking_wait_separately():
    """6.5：汇总表并列展示推理耗时与阻塞等待，不把两者相加为处理时间。"""
    row = make_row(
        0,
        inference_seconds=20.0,
        time={"working": 20.0, "adjusted_working": 20.0, "blocking_wait": 4.0},
    )
    assert row["blocking_wait_seconds"] == 4.0

    dialog = _dialog([row])
    try:
        table = dialog.image_table
        assert _cell(dialog, table, 0, IMAGE_TABLE_COLUMNS,
                     "inference_seconds") == "20.0"
        assert _cell(dialog, table, 0, IMAGE_TABLE_COLUMNS,
                     "blocking_wait_seconds") == "4.0"
        assert _cell(dialog, table, 0, IMAGE_TABLE_COLUMNS,
                     "working_seconds") == "20.0"
    finally:
        dialog.close()
