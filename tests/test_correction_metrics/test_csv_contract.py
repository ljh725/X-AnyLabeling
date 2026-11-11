"""Tasks 8.1 / 8.3 / 8.4 / 8.5 -- the CSV contract, safety and atomicity.

Qt-free: the exporter and the reporting projections are pure services.  The
multi-session and label-JSON cases use the real ``MetricsStore``.
"""

from __future__ import annotations

import csv
import glob
import json
import os

import pytest

from anylabeling.services.correction_metrics import export, reporting
from anylabeling.services.correction_metrics.storage import MetricsStore

from . import synthetic


def _row(**overrides):
    """One fully-populated saved round row."""
    row = {
        "schema_version": 1, "dataset_id": "ds-1",
        "image_path": "D:/data/images/a.jpg", "label_path": "D:/data/labels/a.json",
        "image_digest": "digest-1", "round_id": "round-1",
        "session_ids": ["s1"], "phase": "correction", "origin": "replacement",
        "run_id": "run-1", "model": "yolov8n", "model_version": None,
        "config_digest": "cfg-1", "prompt": "cat, dog",
        "thresholds": {"conf_threshold": 0.25}, "category_version": "cats-1",
        "revision": "rev-1", "current": True, "completed": True,
        "quality": "not-assessed", "comparable": True, "issues": [],
        "baseline_count": 3, "ai_count": 2, "final_count": 3,
        "unsupported_count": 0, "added": 1, "deleted": 1,
        "geometry_changed": 0, "class_changed": 0, "modified_original": 1,
        "unchanged": 1, "modified_rate": 1 / 3, "unchanged_rate": 1 / 3,
        "transactions": 2, "touches": 2, "unique_objects": 2,
        "undo_count": 0, "redo_count": 0, "completion": "completion-1",
        "operation_counts": {"geometry": 1, "delete": 1},
        "time": {"working": 10.0, "adjusted_working": 9.5},
        "inference_seconds": 1.25,
        "classes": [
            {"kind": "initial", "initial_class": "cat", "final_class": "",
             "count": 2, "denominator": 3},
            {"kind": "class_changed", "initial_class": "cat",
             "final_class": "feline", "count": 1, "denominator": 2},
        ],
    }
    row.update(overrides)
    return reporting.saved_row(row)


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


def _raw_text(path):
    return path.read_bytes().decode("utf-8-sig")


def _cells_by_column(path):
    rows = _read_csv(path)
    header = rows[0]
    return header, [dict(zip(header, values)) for values in rows[1:]]


def _tempfiles(directory):
    return glob.glob(os.path.join(str(directory), ".correction-export-*"))


# ---------------------------------------------------------------- 8.1
def test_images_header_is_exactly_the_declared_contract(tmp_path):
    path = tmp_path / "images.csv"
    export.export_csv(path, [_row()], kind="images")
    header, records = _cells_by_column(path)
    assert tuple(header) == export.CSV_COLUMNS["images"]
    assert len(records) == 1
    for column in ("origin", "run_id", "model", "model_version", "image_path",
                   "label_path", "revision", "session_ids", "phase",
                   "completed", "issues", "comparable", "baseline_count",
                   "added", "deleted", "geometry_changed", "class_changed",
                   "transactions", "touches", "unique_objects",
                   "working_seconds", "inference_seconds"):
        assert column in header, column


def test_classes_header_is_exactly_the_declared_contract(tmp_path):
    path = tmp_path / "classes.csv"
    export.export_csv(path, [_row()], kind="classes")
    header, records = _cells_by_column(path)
    assert tuple(header) == export.CSV_COLUMNS["classes"]
    assert len(records) == 2
    assert {r["kind"] for r in records} == {"initial", "class_changed"}
    changed = [r for r in records if r["kind"] == "class_changed"][0]
    assert changed["initial_class"] == "cat"
    assert changed["final_class"] == "feline"
    assert changed["count"] == "1" and changed["denominator"] == "2"
    assert changed["category_version"] == "cats-1"
    assert changed["comparable"] == "True"


def test_dictionary_defines_every_exported_column(tmp_path):
    path = tmp_path / "dictionary.csv"
    export.export_csv(path, [], kind="dictionary")
    header, records = _cells_by_column(path)
    assert tuple(header) == ("field", "meaning")
    defined = {r["field"] for r in records}
    required = set(export.CSV_COLUMNS["images"]) | set(export.CSV_COLUMNS["classes"])
    assert required <= defined, sorted(required - defined)
    assert all(r["meaning"] for r in records if r["field"] in required)
    assert {"N/A", "CSV text"} <= defined


# ---------------------------------------------------------------- 8.2
def test_two_sessions_are_summed_and_appear_once(tmp_path):
    work = synthetic.workdir()
    store = MetricsStore(work / "m.sqlite3", dataset_id="ds")
    try:
        shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10)),
                  synthetic.rect("c-002", "cat", (20, 20, 30, 30))]
        round_obj = store.open_round(str(work / "a.jpg"), str(work / "a.json"),
                                     "digest-a", shapes,
                                     origin="unknown-existing", saved=True)
        round_obj.set_time("s1", {"working": 4.0, "paused": 1.0})
        round_obj.set_time("s2", {"working": 6.5, "paused": 0.5})
        store.flush()
        rows = [reporting.saved_row(row) for row in store.rows()]
    finally:
        store.close()
    assert len(rows) == 1
    assert set(rows[0]["session_ids"]) == {"s1", "s2"}

    path = tmp_path / "multi.csv"
    export.export_csv(path, rows, kind="images")
    _, records = _cells_by_column(path)
    assert len(records) == 1
    assert float(records[0]["working_seconds"]) == pytest.approx(10.5)
    assert float(records[0]["paused_seconds"]) == pytest.approx(1.5)


# ---------------------------------------------------------------- 8.3
def test_file_starts_with_a_utf8_bom(tmp_path):
    path = tmp_path / "bom.csv"
    export.export_csv(path, [_row(prompt="中文，逗号")], kind="images")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    _, records = _cells_by_column(path)
    assert records[0]["prompt"] == "中文，逗号"


def test_comma_quote_newline_and_chinese_roundtrip(tmp_path):
    tricky = 'a,b "quoted"\n第二行,中文'
    path = tmp_path / "tricky.csv"
    export.export_csv(path, [_row(prompt=tricky, model="模型,x")], kind="images")
    _, records = _cells_by_column(path)
    assert records[0]["prompt"] == tricky
    assert records[0]["model"] == "模型,x"
    assert '"a,b ""quoted""' in _raw_text(path)


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "  =1+1",
                                   "\t=1+1", "\n=x"])
def test_formula_like_text_is_escaped_and_reversible(tmp_path, value):
    path = tmp_path / "formula.csv"
    export.export_csv(path, [_row(prompt=value)], kind="images")
    _, records = _cells_by_column(path)
    cell = records[0]["prompt"]
    assert cell.startswith("'"), (value, cell)
    assert cell[1:] == value


def test_none_zero_and_empty_stay_distinguishable(tmp_path):
    path = tmp_path / "null.csv"
    export.export_csv(path, [_row(added=None, model_version=None,
                                  deleted=0, prompt="")], kind="images")
    _, records = _cells_by_column(path)
    row = records[0]
    assert row["added"] == "N/A"
    assert row["model_version"] == "N/A"
    assert row["deleted"] == "0"
    assert row["prompt"] == ""
    assert row["thresholds"] != "N/A"


def test_numbers_are_written_without_quotes(tmp_path):
    path = tmp_path / "numbers.csv"
    export.export_csv(path, [_row(baseline_count=3, added=0)], kind="images")
    raw = _raw_text(path)
    assert ',"3",' not in raw and ",'0'," not in raw
    assert ",3," in raw


# ---------------------------------------------------------------- 8.4
def test_cancel_leaves_no_target_and_no_temporary_file(tmp_path):
    path = tmp_path / "cancelled.csv"
    seen = []

    def cancelled():
        seen.append(True)
        return len(seen) > 2

    with pytest.raises(export.ExportCancelled):
        export.export_csv(path, [_row(), _row(), _row()], kind="images",
                          cancelled=cancelled)
    assert not path.exists()
    assert _tempfiles(tmp_path) == []


def test_cancel_keeps_the_existing_target_byte_identical(tmp_path):
    path = tmp_path / "existing.csv"
    export.export_csv(path, [_row()], kind="images")
    before = path.read_bytes()
    with pytest.raises(export.ExportCancelled):
        export.export_csv(path, [_row(prompt="new")], kind="images",
                          cancelled=lambda: True)
    assert path.read_bytes() == before
    assert _tempfiles(tmp_path) == []


def test_write_failure_leaves_the_old_target_and_no_temporary(tmp_path):
    path = tmp_path / "failed.csv"
    export.export_csv(path, [_row()], kind="images")
    before = path.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    original = export.os.replace
    export.os.replace = boom
    try:
        with pytest.raises(OSError):
            export.export_csv(path, [_row(prompt="new")], kind="images")
    finally:
        export.os.replace = original

    assert path.read_bytes() == before
    assert _tempfiles(tmp_path) == []


def test_success_publishes_and_cleans_the_temporary(tmp_path):
    path = tmp_path / "ok.csv"
    export.export_csv(path, [_row(), _row()], kind="images")
    assert path.exists()
    assert _tempfiles(tmp_path) == []
    _, records = _cells_by_column(path)
    assert len(records) == 2


# ---------------------------------------------------------------- 8.5
def test_view_projection_matches_the_csv_cells(tmp_path):
    rows = [_row(), _row(round_id="round-2", image_path="D:/data/images/b.jpg")]
    path = tmp_path / "same.csv"
    export.export_csv(path, rows, kind="images")
    _, records = _cells_by_column(path)

    columns, view = reporting.view_records(rows, "image")
    assert tuple(columns) == reporting.IMAGE_VIEW
    # Every column the panel shows must exist in the CSV contract.
    assert set(columns) <= set(export.CSV_COLUMNS["images"])
    assert len(view) == len(records) == 2
    for projected, exported in zip(view, records):
        for column in reporting.IMAGE_VIEW:
            expected = projected.get(column)
            cell = exported[column]
            if expected is None:
                assert cell == "N/A", column
            elif isinstance(expected, bool):
                assert cell == str(expected), column
            elif isinstance(expected, (int, float)):
                assert float(cell) == float(expected), column
            else:
                assert cell == str(expected), column


def test_class_details_match_the_class_csv(tmp_path):
    rows = [_row()]
    path = tmp_path / "cls.csv"
    export.export_csv(path, rows, kind="classes")
    _, records = _cells_by_column(path)
    details = list(reporting.class_details(rows[0]))
    assert len(details) == len(records)
    for detail, exported in zip(details, records):
        assert exported["kind"] == detail["kind"]
        assert exported["initial_class"] == detail["initial_class"]
        assert int(exported["count"]) == detail["count"]
        assert int(exported["denominator"]) == detail["denominator"]


def test_export_contains_no_credentials(tmp_path):
    raw_row = {
        "round_id": "round-secret", "revision": "rev-secret",
        "image_path": "a.jpg", "label_path": "a.json",
        "origin": "replacement", "phase": "correction",
        "api_key": "sk-1234567890", "authorization": "Bearer abc",
        "token": "ghp_abcdef",
    }
    row = reporting.saved_row(raw_row)
    path = tmp_path / "secret.csv"
    export.export_csv(path, [row], kind="images")
    text = _raw_text(path).casefold()
    for marker in ("sk-1234567890", "ghp_abcdef", "bearer abc"):
        assert marker.casefold() not in text, marker


def test_label_json_is_never_annotated_with_statistics(tmp_path):
    work = synthetic.workdir()
    label = work / "a.json"
    shapes = [synthetic.rect("c-001", "cat", (0, 0, 10, 10))]
    original = {"version": "2.4.0", "flags": {}, "shapes": shapes,
                "imagePath": "a.jpg", "imageHeight": 100, "imageWidth": 100}
    label.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    before = label.read_bytes()

    store = MetricsStore(work / "m.sqlite3", dataset_id="ds")
    try:
        round_obj = store.open_round(str(work / "a.jpg"), str(label), "digest-a",
                                     shapes, origin="unknown-existing", saved=True)
        token = round_obj.prepare_save(shapes, str(label))
        assert round_obj.saved(token) is True
        assert store.flush() is True
    finally:
        store.close()

    assert label.read_bytes() == before
    written = json.loads(label.read_text(encoding="utf-8"))
    assert set(written) == set(original)
    for word in ("correction", "metrics", "transaction", "round_id", "elapsed"):
        assert word not in json.dumps(written).casefold()
