"""Controller wiring tests: Qt-free, fake host, real SQLite.

These cover the operations ``notify_metrics`` actually calls (``enter_image``,
``edit``, ``prepare_save``/``save_result``, ``discard``, ``leave_image``,
``prediction_applied``) plus the degradation contract: an observer failure
must never raise into the annotation path.
"""

from __future__ import annotations

import types

import pytest

from anylabeling.services.correction_metrics.core import SHAPE_ID
from anylabeling.views.labeling.correction_metrics.controller import (
    CorrectionMetricsController,
    content_digest,
    shape_ids,
)


def rect(shape_id, label="person", box=(10, 10, 40, 60)):
    return {
        SHAPE_ID: shape_id,
        "label": label,
        "shape_type": "rectangle",
        "points": [[box[0], box[1]], [box[2], box[3]]],
    }


def make_host(tmp_path, shapes=(), name="scene.jpg"):
    image = tmp_path / "images" / name
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"fake-image-bytes-" + name.encode())
    labels = tmp_path / "labels"
    labels.mkdir(exist_ok=True)
    host = types.SimpleNamespace(
        filename=str(image),
        output_dir=str(labels),
        canvas=types.SimpleNamespace(shapes=list(shapes)),
    )
    return host


def make_controller(tmp_path, host):
    return CorrectionMetricsController(
        host,
        language="zh_CN",
        storage_root=str(tmp_path / "metrics"),
    )


def started(tmp_path, shapes=()):
    host = make_host(tmp_path, shapes)
    controller = make_controller(tmp_path, host)
    assert controller.start_scope(str(tmp_path / "images"), str(tmp_path / "labels"))
    return controller, host


def test_disabled_controller_is_inert(tmp_path):
    """功能未启动时所有操作都是无副作用的空操作。"""
    host = make_host(tmp_path)
    controller = make_controller(tmp_path, host)

    assert controller.enabled is False
    assert controller.current_row() is None
    assert controller.edit("create", changed=[rect("r1")]) is False
    assert controller.prepare_save("a.json", []) is None
    assert controller.leave_image() is False
    assert controller.rows() == [] and controller.count() == 0


def test_start_scope_creates_the_local_database(tmp_path):
    """启用数据集范围后才建立本地统计库。"""
    controller, _host = started(tmp_path)

    assert controller.enabled is False  # no image entered yet
    database = list((tmp_path / "metrics").glob("*.sqlite3"))
    assert len(database) == 1 and database[0].stat().st_size > 0


def test_enter_image_freezes_the_current_shapes_as_baseline(tmp_path):
    """首次进入图片时按当前内容冻结起点。"""
    shapes = [rect("r1"), rect("r2")]
    controller, _host = started(tmp_path, shapes)

    assert controller.enter_image() is True
    assert controller.enabled is True
    row = controller.current_row()
    assert row["baseline_count"] == 2
    assert row["origin"] == "unknown-existing"
    assert "unknown-origin" in row["issues"]
    assert row["comparable"] is True  # disclosure only


def test_reopening_an_unchanged_image_keeps_the_same_round(tmp_path):
    """重开同一图片不重新冻结起点，也不制造缺口。"""
    controller, _host = started(tmp_path, [rect("r1")])
    assert controller.enter_image() is True
    first = controller.current_row()["round_id"]
    assert controller.leave_image() is True

    assert controller.enter_image() is True
    row = controller.current_row()
    assert row["round_id"] == first
    assert "reopened-round" not in row["issues"]
    assert row["baseline_count"] == 1


def test_edit_records_one_transaction_for_many_objects(tmp_path):
    """一次多对象编辑只累计 1 个事务。"""
    controller, host = started(tmp_path, [rect("r1"), rect("r2")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(12, 12, 44, 66)), rect("r2")]

    assert controller.edit(
        "geometry", changed=host.canvas.shapes[:1], transaction_id="tx-1"
    ) is True
    row = controller.current_row()
    assert row["transactions"] == 1
    assert row["touches"] == 1
    assert row["unique_objects"] == 1
    assert row["geometry_changed"] == 1  # one rectangle actually moved
    assert row["is_draft"] is True


def test_repeated_transaction_id_is_idempotent(tmp_path):
    """同一事务 ID 重复回调只记一次。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1", box=(20, 20, 60, 80))]

    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="same") is True
    assert controller.edit("geometry", changed=host.canvas.shapes,
                           transaction_id="same") is False
    assert controller.current_row()["transactions"] == 1


def test_save_checkpoint_advances_only_on_success(tmp_path):
    """保存成功才推进已保存版本；失败保留草稿。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    host.canvas.shapes = [rect("r1"), rect("r2")]

    token = controller.prepare_save("scene.json", host.canvas.shapes)
    assert token and token["digest"]
    assert controller.save_result(token, True) is True
    saved = controller.current_row(draft=False)
    assert saved["final_count"] == 2
    assert saved["added"] == 1
    assert controller.current_row()["revision"] == token["digest"]

    # A later failed save must not move the saved version.
    host.canvas.shapes = [rect("r1"), rect("r2"), rect("r3")]
    failed = controller.prepare_save("scene.json", host.canvas.shapes)
    assert controller.save_result(failed, False) is False
    assert controller.current_row()["revision"] == token["digest"]
    assert controller.current_row(draft=True)["final_count"] == 3


def test_discard_returns_to_the_saved_version(tmp_path):
    """丢弃草稿回到最后保存版本，但保留过程记录。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    token = controller.prepare_save("scene.json", host.canvas.shapes)
    controller.save_result(token, True)

    host.canvas.shapes = [rect("r1"), rect("r2")]
    controller.edit("create", changed=[rect("r2")], transaction_id="t-create")
    assert controller.current_row(draft=True)["added"] == 1

    assert controller.discard() is True
    assert controller.current_row()["added"] == 0
    assert controller.current_row()["transactions"] >= 1


def test_geometry_signal_without_identity_is_disclosed(tmp_path):
    """无对象 ID 的 geometry 信号不能归属对象，按记录不完整处理。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    assert controller.geometry() is True
    row = controller.current_row()
    assert "unidentified-geometry" in row["issues"]
    # The signal cannot say which object moved, so per-object counts may be
    # incomplete: this stays a blocking gap until the hooks carry object ids.
    assert row["comparable"] is False
    assert row["geometry_changed"] == 0


def test_degraded_observer_never_raises_and_marks_a_gap(tmp_path):
    """观察者故障要显式标记，不能把标注保存拖垮。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    controller.degrade("edit", RuntimeError("boom"))

    assert "boom" in controller.degraded_reason
    row = controller.current_row()
    assert "metrics-observer-error" in row["issues"]
    assert row["comparable"] is False


def test_prediction_applied_starts_a_new_round(tmp_path):
    """应用预测后开新一轮，并记下预测对象与来源。"""
    controller, host = started(tmp_path, [rect("m1"), rect("m2")])
    controller.enter_image()
    first = controller.current_row()["round_id"]

    host.canvas.shapes = [rect("m1"), rect("m2"), rect("a1")]
    result = types.SimpleNamespace(
        provenance={"mode": "additive", "run_id": "run-1", "model": "yolo"}
    )
    assert controller.prediction_applied(result) is True

    row = controller.current_row()
    assert row["round_id"] != first
    assert row["origin"] == "additive"
    assert row["ai_count"] == 3
    assert row["baseline_count"] == 3


def test_stop_closes_the_session_and_further_edits_are_inert(tmp_path):
    """关闭后停止写入，且不抛异常。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    controller.stop()

    assert controller.edit("create", changed=[rect("r9")]) is False
    assert controller.prepare_save("scene.json", []) is None
    controller.stop()  # idempotent


def test_rows_and_count_expose_saved_rounds(tmp_path):
    """汇总读取能看到已保存轮次。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    token = controller.prepare_save("scene.json", host.canvas.shapes)
    controller.save_result(token, True)

    assert controller.count() == 1
    rows = controller.rows()
    assert len(rows) == 1
    assert rows[0]["baseline_count"] == 1


def test_content_digest_changes_with_content_and_shape_ids_are_unique():
    """图片摘要随内容变化；shape id 去重且忽略缺失项。"""
    assert shape_ids([rect("a"), rect("a"), {"label": "x"}]) == ["a"]
    assert shape_ids([{"label": "x"}]) == []


def test_helper_digest_differs_for_different_bytes(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    assert content_digest(first) != content_digest(second)
    assert content_digest(first) == content_digest(first)
    assert content_digest(tmp_path / "missing.bin") == ""
