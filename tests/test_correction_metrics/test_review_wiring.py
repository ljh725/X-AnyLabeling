"""4.7 review-source wiring: review progress is not a frame transaction.

``core.CorrectionRound.review_event`` records a ``review-confirm`` /
``review-undo`` event with ``count_touches=False``, and ``report_row`` keeps
those kinds out of the ``transactions`` total.  ``undo`` events are linked to
the previous transaction by ``CorrectionRound._replace`` (it keeps an id stack
and fills ``undo_of`` when the caller does not pass one).

These tests drive the real controller + SQLite round without Qt.
"""

from __future__ import annotations

import pathlib
import types
from unittest.mock import Mock

import pytest

from anylabeling.views.labeling.correction_metrics.hooks import notify_metrics

from .test_controller import make_host, rect, started

REVIEW_KINDS = ("review-confirm", "review-undo")


def repo_root():
    root = pathlib.Path(__file__).resolve()
    while root != root.parent and not (root / "anylabeling").is_dir():
        root = root.parent
    return root


def host_for(controller):
    return types.SimpleNamespace(
        correction_metrics=controller,
        canvas=types.SimpleNamespace(shapes=[]),
        set_dirty=Mock(),
    )


def test_review_confirm_is_not_a_frame_transaction(tmp_path):
    """确认复核：记录 review-confirm，但不增加事务/触达/去重对象。"""
    controller, _host = started(tmp_path, [rect("r1"), rect("r2")])
    controller.enter_image()
    host = host_for(controller)

    assert notify_metrics(
        host, "review_event", "review-confirm", affected_ids=["r1", "r2"]
    ) is True
    current = controller.current_row()
    assert current["operation_counts"]["review-confirm"] == 1
    assert current["transactions"] == 0
    assert current["touches"] == 0
    assert current["unique_objects"] == 0
    assert current["undo_count"] == 0
    # Review progress must not fabricate an annotation change either.
    assert current["geometry_changed"] == 0
    assert current["is_draft"] is False


def test_review_undo_uses_its_own_excluded_kind(tmp_path):
    """撤销复核进度用 review-undo：单独计数，同样不进事务总数。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    notify_metrics(host_for(controller), "review_event", "review-undo",
                   affected_ids=["r1"])

    current = controller.current_row()
    assert current["operation_counts"]["review-undo"] == 1
    assert current["transactions"] == 0
    assert current["touches"] == 0


def test_reversed_legacy_kind_would_become_a_transaction(tmp_path):
    """反写的 "undo-review" 不在排除表里，会被当成一次框修改事务。

    这就是 label_widget 需要把事件名改成 core 词汇（review-confirm /
    review-undo）的原因；用例锁定该行为，防止悄悄回退。
    """
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    notify_metrics(host_for(controller), "review_event", "undo-review",
                   affected_ids=["r1"])

    current = controller.current_row()
    assert current["operation_counts"]["undo-review"] == 1
    assert current["transactions"] == 1  # wrong vocabulary = counted as edit


def test_undo_event_links_the_previous_transaction(tmp_path):
    """canvas 撤销事件自动带上 undo_of = 最近一次事务 id。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    first = [rect("r1", box=(20, 20, 60, 80))]
    second = [rect("r1", box=(30, 30, 70, 90))]
    controller.edit("geometry", changed=first, transaction_id="tx-1")
    controller.edit("geometry", changed=second, transaction_id="tx-2")

    # The canvas restores the snapshot taken before tx-2.
    assert controller.edit("undo", changed=first) is True

    current = controller.current_row()
    assert current["transactions"] == 2
    assert current["undo_count"] == 1
    controller._store.flush()
    events = controller._store.events(current["round_id"])
    undo = [event for event in events if event["kind"] == "undo"]
    assert len(undo) == 1
    assert undo[0]["undo_of"] == "tx-2"
    assert undo[0]["id"] != "tx-2"


def test_review_hook_is_inert_without_a_controller():
    """统计未启动（correction_metrics=None）时复核钩子不得抛异常。"""
    host = types.SimpleNamespace(correction_metrics=None)
    assert notify_metrics(host, "review_event", "review-confirm",
                          affected_ids=["r1"]) is None


def test_dense_review_workspace_records_confirmations():
    text = (repo_root() / "anylabeling/views/labeling/dense_review/workspace.py").read_text(
        encoding="utf-8"
    )
    assert text.count('"review-confirm"') >= 2


def test_label_widget_uses_core_review_vocabulary():
    text = (repo_root() / "anylabeling/views/labeling/label_widget.py").read_text(
        encoding="utf-8"
    )
    assert '"undo-review"' not in text and '"redo-review"' not in text
    assert '"review-undo"' in text


def test_redo_is_not_counted_as_a_new_correction(tmp_path):
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    forward = [rect("r1", box=(20, 20, 60, 80))]
    controller.edit("geometry", changed=forward, transaction_id="tx-1")
    controller.edit("undo", changed=[rect("r1")])
    controller.edit("redo", changed=forward, transaction_id="tx-redo")

    assert controller.current_row()["transactions"] == 1  # geometry only
