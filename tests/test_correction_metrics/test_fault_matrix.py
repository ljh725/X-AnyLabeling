"""9.3 fault matrix + 9.1 service scenarios (Qt-free, real SQLite).

Every case states the task item it covers.  Failures that expose a production
defect are marked ``xfail(strict=True)`` and described in the report.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import time
import types
from unittest.mock import Mock

import pytest

from anylabeling.services.correction_metrics.storage import MetricsStore

from .test_controller import make_host, rect, started

DB_NAME = "metrics.sqlite"


def store_of(controller):
    return controller._store


def round_id(controller):
    return controller.current_row()["round_id"]


# --------------------------------------------------------------------------
# 9.3 storage faults
# --------------------------------------------------------------------------


def test_exclusive_lock_never_raises_into_the_annotation_path(tmp_path):
    """9.3 独占锁：另一连接 BEGIN EXCLUSIVE 时编辑不抛异常、返回值稳定。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    store = store_of(controller)
    assert store.flush()
    db_path = str(store.path)

    locker = sqlite3.connect(db_path, timeout=0.5, isolation_level=None)
    locker.execute("PRAGMA busy_timeout=100")
    locker.execute("BEGIN EXCLUSIVE")
    try:
        assert controller.edit("geometry", changed=[rect("r1", box=(12, 12, 44, 66))]) is True
        # A save must still be able to proceed: the observer only enqueues.
        assert controller.prepare_save("scene.json", host.canvas.shapes) is not None
        assert controller.current_row() is not None
    finally:
        locker.execute("ROLLBACK")
        locker.close()


def test_locked_write_is_disclosed_as_a_storage_gap(tmp_path):
    """9.3 独占锁：写入失败必须留 storage-gap，不能静默丢失。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    round_id_ = round_id(controller)
    store = store_of(controller)
    assert store.flush()
    db_path = str(store.path)

    locker = sqlite3.connect(db_path, timeout=0.5, isolation_level=None)
    locker.execute("PRAGMA busy_timeout=100")
    locker.execute("BEGIN EXCLUSIVE")
    try:
        controller.edit("geometry", changed=[rect("r1", box=(13, 13, 45, 67))])
        store.flush(timeout=0.5)
    finally:
        locker.execute("ROLLBACK")
        locker.close()

    assert "storage-gap" in store.gaps(round_id_)
    assert store.error is not None


def test_read_only_database_degrades_and_recovers(tmp_path):
    """9.3 只读库：打开/写入降级但 error 可见；恢复可写后新会话能继续写。"""
    first, _host = started(tmp_path, [rect("r1")])
    first.enter_image()
    db_path = str(store_of(first).path)
    first.stop()

    os.chmod(db_path, stat.S_IREAD)
    try:
        blocked = MetricsStore(db_path, dataset_id="ds-readonly")
        try:
            blocked.open_round(
                str(tmp_path / "images/scene.jpg"),
                str(tmp_path / "labels/scene.json"),
                "digest",
                [rect("r1")],
            )
            blocked.flush(timeout=1.0)
        except sqlite3.Error:
            pass  # a loud failure is acceptable; silence is not
        assert blocked.error is not None, "read-only store must expose its error"
        blocked.close()
    finally:
        os.chmod(db_path, stat.S_IWRITE | stat.S_IREAD)

    again, _host2 = started(tmp_path, [rect("r1")])
    assert again.enter_image() is True
    again.stop()


def test_disk_io_error_is_recorded_not_swallowed(tmp_path, monkeypatch):
    """9.3 磁盘错误：sqlite 抛 disk I/O error 时留缺口、不抛给调用方。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    round_id_ = round_id(controller)
    store = store_of(controller)

    from anylabeling.services.correction_metrics import storage as storage_module

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(storage_module.MetricsStore, "_write", broken)
    try:
        assert controller.edit("geometry", changed=[rect("r1", box=(21, 21, 61, 81))]) is True
        store.flush(timeout=0.5)
    finally:
        monkeypatch.undo()

    assert "storage-gap" in store.gaps(round_id_)
    assert store.error is not None
    # Annotation saving is independent of the statistics failure.
    assert controller.prepare_save("scene.json", host.canvas.shapes) is not None


def test_saturated_queue_records_a_gap_instead_of_dropping(tmp_path):
    """9.3 队列饱和（queue_size=1）：爆量事务只记缺口，不静默丢失。"""
    store = MetricsStore(tmp_path / DB_NAME, dataset_id="ds-saturated", queue_size=1)
    assert store.error is None, store.error
    try:
        obj = store.open_round(
            str(tmp_path / "images/scene.png"),
            str(tmp_path / "labels/scene.json"),
            "digest",
            [rect("r1")],
        )
        for index in range(200):
            obj.patch(
                shapes=[rect("r1", box=(index, index, index + 10, index + 10))],
                kind="geometry",
            )
        store.flush(timeout=2.0)
        assert "storage-gap" in store.gaps(obj.round_id)
    finally:
        store.close()


def test_storage_gap_reaches_the_row_and_makes_it_incomparable(tmp_path):
    """9.3 缺口可见：storage-gap 进入 row() 并使 comparable 为 False。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    store = store_of(controller)

    store._fault(round_id(controller), RuntimeError("disk I/O error"))

    row = controller.current_row()
    assert "storage-gap" in row["issues"]
    assert row["comparable"] is False


# --------------------------------------------------------------------------
# 9.3 crash recovery
# --------------------------------------------------------------------------


def test_matching_pending_checkpoint_restores_the_saved_version(tmp_path):
    """9.3 崩溃恢复：pending 摘要匹配 → 恢复为已保存，不谎报完成。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    shapes = [rect("r1", box=(20, 20, 60, 80))]
    token = controller.prepare_save("scene.json", shapes)
    assert controller.save_result(token, True) is True
    saved_revision = controller.current_row()["revision"]
    controller.stop()

    reopened, host2 = started(tmp_path, shapes)
    host2.canvas.shapes = shapes
    assert reopened.enter_image() is True
    row = reopened.current_row()
    assert row["revision"] == saved_revision
    assert row["completed"] is False


def test_changed_file_on_reopen_flags_external_annotation_change(tmp_path):
    """9.3 崩溃恢复：磁盘内容与 pending 不符 → external-annotation-change。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    token = controller.prepare_save("scene.json", [rect("r1", box=(20, 20, 60, 80))])
    assert controller.save_result(token, True) is True
    controller.stop()

    changed = [rect("r1", box=(90, 90, 120, 140)), rect("r2")]
    reopened, host2 = started(tmp_path, changed)
    host2.canvas.shapes = changed
    assert reopened.enter_image() is True
    row = reopened.current_row()
    assert "external-annotation-change" in row["issues"]
    assert row["completed"] is False


# --------------------------------------------------------------------------
# 9.3 statistics failure never blocks saving
# --------------------------------------------------------------------------


def test_metrics_failure_never_blocks_annotation_saving(tmp_path):
    """9.3 统计故障不拖垮标注保存：hooks 吞异常，保存流程继续返回成功。"""
    from anylabeling.views.labeling.correction_metrics.hooks import notify_metrics

    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    controller.degrade("edit", RuntimeError("boom"))
    host.correction_metrics = controller

    saved = {"value": False}

    def fake_save_file():
        notify_metrics(host, "prepare_save", "scene.json", host.canvas.shapes)
        notify_metrics(host, "edit", "geometry", changed=[rect("r1")])
        notify_metrics(host, "save_result", None, True)
        saved["value"] = True
        return True

    assert fake_save_file() is True
    assert saved["value"] is True
    assert controller.degraded_reason is not None


def test_broken_store_still_allows_a_successful_save(tmp_path, monkeypatch):
    """9.3 统计库彻底不可用：保存仍然成功（观察者不能反向影响标注）。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    def explode(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    from anylabeling.views.labeling.correction_metrics.hooks import notify_metrics

    monkeypatch.setattr(store_of(controller), "_enqueue", explode)
    host.correction_metrics = controller
    saved = {"value": False}

    def save_file():
        notify_metrics(host, "prepare_save", "scene.json", host.canvas.shapes)
        assert controller.edit("geometry", changed=[rect("r1", box=(5, 5, 15, 15))]) is False
        notify_metrics(host, "save_result", None, True)
        saved["value"] = True
        return True

    assert save_file() is True
    assert saved["value"] is True
    assert controller.degraded_reason is not None


# --------------------------------------------------------------------------
# 9.3 export must not pass a draft off as a delivered result
# --------------------------------------------------------------------------


def test_export_never_presents_an_unsaved_draft(tmp_path):
    """9.3 导出：仅有草稿的轮次 final_count 为空且带 unsaved-result。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    controller.edit("geometry", changed=[rect("r1", box=(20, 20, 60, 80))])

    from anylabeling.services.correction_metrics import core, reporting

    store = MetricsStore(tmp_path / DB_NAME, dataset_id="ds-draft")
    try:
        obj = store.open_round(
            str(tmp_path / "images/scene.png"),
            str(tmp_path / "labels/scene.json"),
            "digest",
            [rect("r1")],
            saved=False,
        )
        obj.patch(shapes=[rect("r1", box=(20, 20, 60, 80))], kind="geometry")
        draft = reporting.saved_row(core.report_row(obj._state))
    finally:
        store.close()

    assert draft["final_count"] is None
    assert draft["comparable"] is False
    assert "unsaved-result" in draft["issues"]


def test_export_after_a_save_carries_final_quantities(tmp_path):
    """9.3 导出：已保存轮次带最终计数。"""
    controller, host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    shapes = [rect("r1", box=(20, 20, 60, 80))]
    token = controller.prepare_save("scene.json", shapes)
    assert controller.save_result(token, True) is True

    row = controller.rows()[0]
    assert row["final_count"] == 1
    assert row["revision"]
    assert "unsaved-result" not in row["issues"]


# --------------------------------------------------------------------------
# 9.1 service scenarios not covered by the existing suites
# --------------------------------------------------------------------------


def test_s91_class_and_geometry_change_in_one_transaction(tmp_path):
    """9.1 改类/改框重叠：同一事务既改类又改框，两类计数都记一次。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    controller.edit(
        "edit",
        changed=[rect("r1", label="car", box=(20, 20, 60, 80))],
        transaction_id="both",
    )

    row = controller.current_row()
    assert row["transactions"] == 1
    assert row["touches"] == 1
    assert row["geometry_changed"] == 1
    assert row["class_changed"] == 1


def test_s91_undo_returns_to_the_starting_net_result(tmp_path):
    """9.1 撤销回起点：过程留痕，净结果归零。"""
    controller, _host = started(tmp_path, [rect("r1"), rect("r2")])
    controller.enter_image()
    baseline = [rect("r1"), rect("r2")]

    controller.edit("geometry", changed=[rect("r1", box=(30, 30, 70, 90))])
    controller.edit("undo", changed=baseline)

    row = controller.current_row()
    assert row["undo_count"] == 1
    assert row["geometry_changed"] == 0
    assert row["added"] == 0 and row["deleted"] == 0


def test_s91_created_then_deleted_keeps_the_process_cost(tmp_path):
    """9.1 新增再删：过程计数保留，净结果归零。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    controller.edit("create", changed=[rect("r1"), rect("r2")])
    controller.edit("delete", removed=[rect("r2")])

    row = controller.current_row()
    assert row["transactions"] == 2
    assert row["added"] == 0 and row["deleted"] == 0
    assert row["final_count"] == 1


def test_s91_micro_coordinate_change_is_still_a_correction(tmp_path):
    """9.1 微坐标：1px 调整也算一次真实改框。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()

    controller.edit("geometry", changed=[rect("r1", box=(11, 10, 40, 60))])

    row = controller.current_row()
    assert row["geometry_changed"] == 1
    assert row["transactions"] == 1


def test_s91_zero_object_image_has_no_rates_and_stays_comparable(tmp_path):
    """9.1 零对象：空图不产生比例，也不因此不可比。"""
    controller, _host = started(tmp_path, [])
    controller.enter_image()

    row = controller.current_row()
    assert row["baseline_count"] == 0
    assert row["final_count"] == 0
    assert row["modified_rate"] is None
    assert row["comparable"] is True


def test_s91_mixed_scope_makes_the_round_incomplete(tmp_path):
    """9.1 混合范围：含非矩形对象时标 partial-scope 且不可比。"""
    mixed = [rect("r1"), {"label": "poly", "shape_type": "polygon",
                          "points": [[0, 0], [10, 0], [10, 10]],
                          "xanylabeling_shape_id": "p1"}]
    controller, _host = started(tmp_path, mixed)
    controller.enter_image()

    row = controller.current_row()
    assert "partial-scope" in row["issues"]
    assert row["comparable"] is False


# --------------------------------------------------------------------------
# 3.3 recovery entry: retry after a transient storage fault
# --------------------------------------------------------------------------
def test_retry_reopens_a_dead_writer_and_keeps_recording(tmp_path):
    """3.3 恢复入口：写入线程退出后 retry 重新起线程，后续事务仍能落库。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    store = store_of(controller)
    # Simulate a crashed writer: the thread ends without closing the store.
    store._queue.put(None)
    store._thread.join(2.0)
    assert not store._thread.is_alive()

    assert store.retry() is True
    assert store.error is None

    assert controller.edit(
        "geometry", changed=[rect("r1", box=(31, 31, 71, 91))]
    ) is True
    assert store.flush(timeout=2.0) is True
    assert controller.current_row()["geometry_changed"] == 1


def test_retry_never_hides_a_recorded_gap(tmp_path):
    """3.3 恢复：重试只清除粘性错误，已记录的缺口仍然可见。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    round_id_ = round_id(controller)
    store = store_of(controller)
    store._queue.put(None)
    store._thread.join(2.0)
    store._fault(round_id_, RuntimeError("disk I/O error"))
    assert store.error is not None

    assert store.retry() is True

    assert store.error is None
    assert "storage-gap" in store.gaps(round_id_)
    assert "storage-gap" in controller.current_row()["issues"]


def test_controller_retry_clears_the_degraded_banner(tmp_path):
    """3.3 恢复入口：controller.retry_storage 成功后不再显示记录异常。"""
    controller, _host = started(tmp_path, [rect("r1")])
    controller.enter_image()
    store = store_of(controller)
    store._queue.put(None)
    store._thread.join(2.0)
    store.error = "disk I/O error"

    assert controller.degraded_reason.startswith("storage:")
    assert controller.retry_storage() is True
    assert controller.degraded_reason is None
