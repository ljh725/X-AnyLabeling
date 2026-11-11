"""Snapshot export and annotation-integrity checks (8.2 / 8.5, lead-owned).

* an export must use the snapshot the caller froze, even if new rounds are
  recorded afterwards;
* recording statistics must never mutate the annotation payload or write to
  the label file.
"""

from __future__ import annotations

import copy
import csv
import json

from tests.test_correction_metrics.test_controller import rect, started


def _save(controller, host):
    token = controller.prepare_save("scene.json", host.canvas.shapes)
    assert controller.save_result(token, True) is True
    return token


def test_export_uses_the_frozen_snapshot_after_new_rounds(tmp_path):
    """8.2：导出只包含调用方冻结的那批行，后续新轮次不会混入。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)
    frozen = controller.rows()
    assert len(frozen) == 1

    other = tmp_path / "images" / "later.jpg"
    other.write_bytes(b"later-image")
    assert controller.prediction_saved(
        str(other),
        str(tmp_path / "labels" / "later.json"),
        {"run_id": "later-run"},
        [rect("a1")],
    ) is True
    assert len(controller.rows()) == 2  # the live view sees both

    target = tmp_path / "frozen.csv"
    assert controller.export("images", str(target), rows=frozen) is not False

    with target.open("r", encoding="utf-8-sig", newline="") as stream:
        parsed = list(csv.DictReader(stream))
    assert len(parsed) == 1
    assert parsed[0]["image_path"] == frozen[0]["image_path"]
    assert "later-run" not in {row.get("run_id") for row in parsed}


def test_export_without_a_snapshot_reads_the_current_rows(tmp_path):
    """未传 rows 时导出当前行（默认行为保持可用）。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)
    target = tmp_path / "live.csv"

    assert controller.export("images", str(target)) is not False

    with target.open("r", encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == controller.count()


def test_recording_never_mutates_annotation_shapes(tmp_path):
    """8.5：统计只观察，不修改传入的标注对象/字典。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    shapes = [rect("r1", box=(50, 50, 90, 90))]
    before = copy.deepcopy(shapes)

    assert controller.edit("geometry", changed=shapes,
                           transaction_id="tx-move") is True

    assert shapes == before
    for shape in shapes:
        assert set(shape) == {"xanylabeling_shape_id", "label", "shape_type",
                              "points"}


def test_recording_never_writes_the_label_file(tmp_path):
    """8.5：统计链路不写标注 JSON（保存由原有 LabelFile 完成）。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    label = tmp_path / "labels" / "scene.json"
    original = json.dumps({"shapes": [rect("r1")]}, ensure_ascii=False)
    label.write_text(original, encoding="utf-8")

    token = controller.prepare_save(str(label), host.canvas.shapes)
    assert controller.save_result(token, True) is True
    controller.edit("create", changed=[rect("r2")])
    controller.discard()

    assert label.read_text(encoding="utf-8") == original


def test_saved_rows_carry_no_draft_values(tmp_path):
    """8.5：未保存草稿不得出现在已保存行/导出里冒充交付结果。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    _save(controller, host)
    host.canvas.shapes = [rect("r1"), rect("r2")]
    controller.edit("create", changed=[rect("r2")])

    saved = controller.current_row(draft=False)
    assert saved["added"] == 0
    assert saved["final_count"] == 1
    draft = controller.current_row(draft=True)
    assert draft["added"] == 1
    assert draft["is_draft"] is True

    target = tmp_path / "rows.csv"
    controller.export("images", str(target))
    with target.open("r", encoding="utf-8-sig", newline="") as stream:
        parsed = list(csv.DictReader(stream))
    assert [row["added"] for row in parsed] == ["0"]
