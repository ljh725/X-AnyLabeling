"""Geometry completion-boundary wiring: one user action -> one transaction.

``LabelingWidget._on_geometry_committed`` is the single slot connected to
``Canvas.shape_moved`` (label_widget.py:682).  It hands the whole canvas to
``edit(kind="geometry", changed=...)`` so the round can diff those shapes
against its draft and keep only the objects that really moved.

These tests call the real slot unbound on a fake host, so the real controller
and its SQLite round are exercised without a window or a QApplication.

Install as ``tests/test_correction_metrics/test_geometry_wiring.py`` (the
relative import of the shared helpers below expects that package), then run::

    python -m pytest tests/test_correction_metrics/test_geometry_wiring.py -q
"""

from __future__ import annotations

import types
from unittest.mock import Mock

from anylabeling.views.labeling.correction_metrics.controller import (
    CorrectionMetricsController,
)
from anylabeling.views.labeling.label_widget import LabelingWidget

from .test_controller import make_host, rect, started


def commit(controller, shapes):
    """Run the real completion slot once with the given canvas contents."""
    host = types.SimpleNamespace(
        canvas=types.SimpleNamespace(shapes=list(shapes)),
        correction_metrics=controller,
        set_dirty=Mock(),
    )
    LabelingWidget._on_geometry_committed(host)
    return host


def row(controller):
    return controller.current_row()


def test_two_moved_objects_are_exactly_one_transaction(tmp_path):
    """拖动两个框：1 事务 / 触达 2 / 去重 2 / 几何变化 2。"""
    controller, _host = started(tmp_path, [rect("r1"), rect("r2")])
    assert controller.enter_image() is True
    moved = [
        rect("r1", box=(20, 20, 60, 80)),
        rect("r2", box=(70, 70, 120, 130)),
    ]

    host = commit(controller, moved)

    current = row(controller)
    assert current["transactions"] == 1
    assert current["touches"] == 2
    assert current["unique_objects"] == 2
    assert current["geometry_changed"] == 2
    assert current["added"] == 0 and current["deleted"] == 0
    # Identity is carried now: the round must not fall back to the legacy
    # "unidentified geometry" gap.
    assert "unidentified-geometry" not in current["issues"]
    assert current["comparable"] is True
    assert current["is_draft"] is True
    host.set_dirty.assert_called_once_with()


def test_only_the_object_that_moved_is_counted(tmp_path):
    """槽传入画布全部对象，但只有真正移动的框计数（未变化/锁定对象不计）。"""
    controller, _host = started(
        tmp_path, [rect("r1"), rect("r2"), rect("r3")]
    )
    controller.enter_image()
    # r1 and r3 are untouched: r1 stands in for a locked object, r3 for a
    # merely unaffected selected neighbour.
    after = [
        rect("r1"),
        rect("r2", box=(15, 15, 50, 70)),
        rect("r3"),
    ]

    commit(controller, after)

    current = row(controller)
    assert current["transactions"] == 1
    assert current["touches"] == 1
    assert current["unique_objects"] == 1
    assert current["geometry_changed"] == 1


def test_commit_without_any_geometry_change_records_nothing(tmp_path):
    """浮层点击/未移动：差集为空，不产生事务，但仍标记脏图。"""
    controller, _host = started(tmp_path, [rect("r1"), rect("r2")])
    controller.enter_image()

    host = commit(controller, [rect("r1"), rect("r2")])

    current = row(controller)
    assert current["transactions"] == 0
    assert current["touches"] == 0
    assert current["unique_objects"] == 0
    assert current["geometry_changed"] == 0
    # Nothing changed, so the draft still equals the saved baseline.
    assert current["is_draft"] is False
    host.set_dirty.assert_called_once_with()


def test_repeating_the_same_commit_does_not_add_a_transaction(tmp_path):
    """同一手势被重复通知（例如 leaveEvent 已提交后又来一次 release）只记一次。"""
    controller, _host = started(tmp_path, [rect("r1"), rect("r2")])
    controller.enter_image()
    after = [rect("r1", box=(20, 20, 60, 80)), rect("r2")]

    commit(controller, after)
    first = row(controller)["transactions"]
    commit(controller, after)
    commit(controller, after)

    current = row(controller)
    assert first == 1
    assert current["transactions"] == 1
    assert current["touches"] == 1
    assert current["geometry_changed"] == 1


def test_multi_select_edge_drag_changes_one_rectangle_once(tmp_path):
    """多选状态下拖边只改一个框：1 事务 / 1 对象，另一个选中框不计。"""
    controller, _host = started(tmp_path, [rect("r1"), rect("r2")])
    controller.enter_image()
    # Edge drag on r1 only; r2 stays as it was even though it is selected.
    after = [rect("r1", box=(10, 10, 60, 60)), rect("r2")]

    commit(controller, after)

    current = row(controller)
    assert current["transactions"] == 1
    assert current["touches"] == 1
    assert current["unique_objects"] == 1
    assert current["geometry_changed"] == 1


def test_keyboard_nudge_is_one_transaction_per_release(tmp_path):
    """方向键微调经由同一槽：每次松开 1 事务 / 1 对象。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    commit(controller, [rect("r1", box=(11, 10, 41, 60))])
    assert row(controller)["transactions"] == 1
    assert row(controller)["touches"] == 1
    assert row(controller)["geometry_changed"] == 1

    commit(controller, [rect("r1", box=(12, 10, 42, 60))])
    assert row(controller)["transactions"] == 2
    assert row(controller)["touches"] == 2


def test_shift_and_shift_alt_fit_go_through_the_same_slot(tmp_path):
    """两种单点拟合都只发一次 shape_moved，因此与拖动共用同一完成边界。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    # Shift fit moves the picked corner; Shift+Alt fits inward.
    commit(controller, [rect("r1", box=(10, 10, 55, 65))])
    commit(controller, [rect("r1", box=(20, 20, 45, 55))])

    current = row(controller)
    assert current["transactions"] == 2
    assert current["touches"] == 2
    assert current["unique_objects"] == 1
    assert current["geometry_changed"] == 1  # net: still one rectangle


def test_slot_is_inert_when_the_controller_is_disabled(tmp_path):
    """统计未启动时槽不得抛异常，也不能阻止 set_dirty。"""
    base = make_host(tmp_path, [rect("r1")])
    controller = CorrectionMetricsController(
        base, language="zh_CN", storage_root=str(tmp_path / "metrics-disabled")
    )
    assert controller.enabled is False

    host = commit(controller, [rect("r1", box=(30, 30, 70, 90))])

    assert controller.current_row() is None
    host.set_dirty.assert_called_once_with()
