"""5.2/6.2 navigation cancel + lifecycle: cancelling keeps the round and its time.

The Qt widget is not needed: these drive the real controller (and its real
SQLite round) the way the label widget's hooks do, then assert the lifecycle
invariants a cancelled navigation must not break.
"""

from __future__ import annotations

import types

import pytest

from anylabeling.views.labeling.correction_metrics.controller import (
    CorrectionMetricsController,
)
from anylabeling.views.labeling.correction_metrics.hooks import notify_metrics

from .test_controller import make_host, rect, started


def row(controller):
    return controller.current_row()


def other_image(tmp_path, name="next.jpg"):
    image = tmp_path / "images" / name
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"second-image-" + name.encode())
    return str(image)


def test_cancelled_navigation_keeps_the_round_and_leaves_no_trace(tmp_path):
    """取消切图：round_id 不变，且没有为目标图开新轮次。"""
    controller, host = started(tmp_path, [rect("r1")])
    assert controller.enter_image() is True
    round_id = row(controller)["round_id"]

    # Cancel path: the widget never calls leave_image/enter_image.
    host.filename = other_image(tmp_path)  # pretend the widget bound the file

    assert row(controller)["round_id"] == round_id
    # The abandoned target never became a round: the store still holds exactly
    # the one open draft the user is looking at.
    rows = controller.rows()
    assert len(rows) == 1 and rows[0]["round_id"] == round_id
    assert all(r["image_path"] != host.filename for r in rows)
    assert controller._round.image_path == row(controller)["image_path"]


def test_cancelled_navigation_does_not_move_working_time(tmp_path):
    """取消切图不改变当前轮次的时间归属（同一轮、同一路径、同一时间）。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    before = row(controller)

    host.filename = other_image(tmp_path)  # the widget reverts and returns

    after = row(controller)
    assert after["round_id"] == before["round_id"]
    assert after["image_path"] == before["image_path"]
    assert after["time"] == before["time"]
    assert after["image_path"] == controller._round.image_path


def test_navigation_cancelled_hook_is_inert_without_controller():
    """未启用统计时 navigation_cancelled 钩子不抛异常。"""
    host = types.SimpleNamespace(correction_metrics=None)
    assert notify_metrics(host, "navigation_cancelled") is None


def test_discard_then_leave_keeps_the_abandoned_round_queryable(tmp_path):
    """丢弃后切图：旧轮次仍可查，新图开启新轮次。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    first = row(controller)["round_id"]
    controller.edit("geometry", changed=[rect("r1", box=(20, 20, 60, 80))])

    assert controller.discard() is True
    assert controller.leave_image() is True

    host.filename = other_image(tmp_path)
    assert controller.enter_image() is True
    assert row(controller)["round_id"] != first
    assert first in {r["round_id"] for r in controller.rows()}


def test_leave_then_enter_switches_round_and_keeps_the_old_one(tmp_path):
    """正常切图：leave→enter 换轮次，旧轮次仍可查。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    first = row(controller)["round_id"]
    assert controller.leave_image() is True

    host.filename = other_image(tmp_path)
    assert controller.enter_image() is True
    assert row(controller)["round_id"] != first
    assert first in {r["round_id"] for r in controller.rows()}


def test_stop_is_idempotent_and_disables_further_edits(tmp_path):
    """关闭：stop() 后 enabled False、edit 返回 False，重复 stop 幂等。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    assert controller.stop() is None
    assert controller.enabled is False
    assert controller.edit("geometry", changed=[rect("r1", box=(9, 9, 19, 19))]) is False
    assert controller.prepare_save("x.json", []) is None
    assert controller.enter_image() is False
    assert controller.stop() is None  # must not raise


def test_stop_flushes_the_round_and_closes_the_store(tmp_path):
    """关闭时库被 flush 并关闭；已保存轮次能被新会话读回。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    round_id = row(controller)["round_id"]
    token = controller.prepare_save("scene.json", host.canvas.shapes)
    assert controller.save_result(token, True) is True

    controller.stop()

    assert controller._store is None
    assert controller.current_row() is None
    assert controller.count() == 0  # closed: no live store to count through

    fresh_host = make_host(tmp_path, [rect("r1")])
    fresh = CorrectionMetricsController(
        fresh_host, language="zh_CN", storage_root=str(tmp_path / "metrics")
    )
    assert fresh.start_scope(str(tmp_path / "images"), str(tmp_path / "labels"))
    try:
        assert round_id in {r["round_id"] for r in fresh.rows()}
    finally:
        fresh.stop()


def test_enter_without_a_loaded_image_is_inert(tmp_path):
    """没有图片时 enter_image 不建轮次（导航到空目录）。"""
    host = make_host(tmp_path, [rect("r1")])
    host.filename = ""
    controller = CorrectionMetricsController(
        host, language="zh_CN", storage_root=str(tmp_path / "metrics-empty")
    )

    assert controller.enter_image() is False
    assert controller.current_row() is None


def test_reopening_the_same_image_reuses_the_round(tmp_path):
    """取消后又点同一张：沿用原轮次，不制造 reopened 缺口。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    round_id = row(controller)["round_id"]

    assert controller.leave_image() is True
    assert controller.enter_image() is True

    assert row(controller)["round_id"] == round_id
    assert "reopened-round" not in row(controller)["issues"]


def test_may_continue_cancel_branch_discloses_the_attempt():
    import pathlib

    root = pathlib.Path(__file__).resolve()
    while root != root.parent and not (root / "anylabeling").is_dir():
        root = root.parent
    text = (root / "anylabeling/views/labeling/label_widget.py").read_text(
        encoding="utf-8"
    )
    assert "navigation_cancelled" in text
