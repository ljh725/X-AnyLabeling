"""Tasks 3.1-3.3 -- SQLite schema, refusal to open foreign versions, round
persistence, event outcomes, flush barrier, close and queue saturation.

Covers spec ``STO-1`` (local history with a schema version), ``STO-2``
(refuse an unknown/future database instead of overwriting it), ``STO-3``
(a write failure is disclosed as ``storage-gap`` and never silently dropped)
and ``BASE-6`` (statistics are stored outside the annotation JSON).
"""

from __future__ import annotations

import sqlite3

import pytest

from anylabeling.services.correction_metrics.core import SCHEMA_VERSION
from anylabeling.services.correction_metrics.storage import MetricsStore

from . import synthetic

DB_NAME = "metrics.sqlite"


def image_pair(tmp_path):
    """Return stable image/label paths inside the test's temp directory."""
    return (str(tmp_path / "images" / "scene.png"),
            str(tmp_path / "labels" / "scene.json"))


def open_store(tmp_path, **kwargs):
    """Open a healthy ``MetricsStore`` or fail loudly with its error message."""
    store = MetricsStore(tmp_path / DB_NAME, dataset_id="ds-storage", **kwargs)
    assert store.error is None, store.error
    return store


def test_new_database_creates_all_tables_with_schema_version(tmp_path):
    """验证 STO-1：新库自动建 rounds/events/revisions/completions/predictions 并写 user_version。"""
    store = open_store(tmp_path)
    store.close()

    db = sqlite3.connect(tmp_path / DB_NAME)
    try:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"rounds", "events", "revisions", "completions",
                "predictions"} <= tables
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert SCHEMA_VERSION == 1
    finally:
        db.close()


def test_version_mismatch_is_refused_without_overwriting_the_file(tmp_path):
    """验证 STO-2：user_version=99 的库必须拒绝打开、不启动写入线程、不覆盖原数据。"""
    path = tmp_path / "future.sqlite"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE sentinel(value TEXT)")
    raw.execute("INSERT INTO sentinel VALUES('keep-me')")
    raw.execute("PRAGMA user_version=99")
    raw.commit()
    raw.close()

    store = MetricsStore(path)

    assert store.error is not None
    assert "99" in store.error
    assert store._thread is None
    assert store.flush() is False

    raw = sqlite3.connect(path)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 99
        assert raw.execute("SELECT value FROM sentinel").fetchone()[0] == "keep-me"
        tables = {row[0] for row in raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "rounds" not in tables
    finally:
        raw.close()


@pytest.mark.parametrize("path", [
    "//fileserver/share/metrics.sqlite",
    r"\\fileserver\share\metrics.sqlite",
])
def test_network_path_is_refused(tmp_path, path):
    """验证 STO-1：UNC 网络路径不被接受，统计库必须是本地文件。"""
    store = MetricsStore(path)

    assert store.error is not None
    assert "local database" in store.error
    assert store._thread is None


def test_open_round_is_readable_through_rows_count_latest_and_open_existing(tmp_path):
    """验证 STO-1：open_round 落库后 rows/count/latest/open_existing 读回同一 round_id。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    shapes = synthetic.occluded_small()

    round_obj = store.open_round(image, label, "digest-a", shapes,
                                 origin="replacement", predicted_ids=("o-001",))
    assert store.flush() is True
    assert store.count() == 1

    rows = store.rows(limit=10)
    assert len(rows) == 1
    assert rows[0]["round_id"] == round_obj.round_id
    assert rows[0]["baseline_count"] == 12
    assert rows[0]["ai_count"] == 1
    assert rows[0]["current"] is True

    assert store.latest(image, label).round_id == round_obj.round_id
    assert store.open_existing(round_obj.round_id).round_id == round_obj.round_id
    store.close()


def test_event_outcome_moves_from_draft_to_saved(tmp_path):
    """验证 STO-1：patch 事件先落库为 draft，成功 saved() 后同一事件转为 saved。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    shapes = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", shapes,
                                 origin="replacement")
    shape = synthetic.by_id(shapes)["o-001"]

    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    assert store.flush() is True
    events = store.events(round_obj.round_id)
    assert [event["kind"] for event in events] == ["geometry"]
    assert [event["outcome"] for event in events] == ["draft"]
    assert events[0]["id"] == "tx-1"

    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    assert round_obj.saved(token) is True
    assert store.flush() is True
    assert [event["outcome"] for event in store.events(round_obj.round_id)] == ["saved"]
    store.close()


def test_discarded_draft_marks_its_events_discarded(tmp_path):
    """验证 STO-1：discard() 后草稿阶段事件在库中标记为 discarded，轮次回到已保存版本。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    shapes = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", shapes,
                                 origin="replacement")
    shape = synthetic.by_id(shapes)["o-001"]

    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    assert store.flush() is True
    assert round_obj.discard() is True
    assert store.flush() is True

    events = store.events(round_obj.round_id)
    assert [event["kind"] for event in events] == ["geometry", "discard"]
    assert [event["outcome"] for event in events] == ["discarded", "discarded"]
    assert round_obj.dirty is False
    assert round_obj.saved_revision == round_obj.row()["revision"]
    store.close()


def test_flush_is_a_barrier_and_close_stops_writes_with_a_gap(tmp_path):
    """验证 STO-3：flush() 屏障返回 True；close() 后写入失败并记录 storage-gap。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    shapes = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", shapes,
                                 origin="replacement")
    assert store.flush() is True

    store.close()

    assert store.flush() is False
    shape = synthetic.by_id(shapes)["o-001"]
    round_obj.patch(shapes=[synthetic.moved(shape, 3, 3)],
                    transaction_id="after-close")
    assert "storage-gap" in store.gaps(round_obj.round_id)
    assert store.error is not None
    row = round_obj.row(draft=True)
    assert "storage-gap" in row["issues"]
    assert row["comparable"] is False


def test_saturated_queue_records_a_storage_gap_instead_of_dropping(tmp_path):
    """验证 STO-3：queue_size=1 灌入大量事务时队列饱和被记录为 storage-gap，不静默丢失。"""
    store = open_store(tmp_path, queue_size=1)
    image, label = image_pair(tmp_path)
    shapes = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", shapes,
                                 origin="replacement")

    for index in range(200):
        # Every patch changes geometry, so each one really reaches the queue.
        round_obj.patch(
            shapes=[synthetic.rect("o-001", "cat", (20 + index, 20, 28 + index, 28))],
            transaction_id="saturate-%03d" % index,
        )

    assert "storage-gap" in store.gaps(round_obj.round_id)
    assert store.error is not None
    row = round_obj.row(draft=True)
    assert "storage-gap" in row["issues"]
    assert row["comparable"] is False
    store.close(timeout=1)


def test_rows_paginate_newest_first(tmp_path):
    """验证 STO-1：rows(limit/offset) 按最新优先分页返回轮次，count 为轮次总数。"""
    store = open_store(tmp_path)
    image = str(tmp_path / "images" / "scene.png")
    created = []
    for index in range(3):
        label = str(tmp_path / "labels" / ("scene-%d.json" % index))
        created.append(store.open_round(image, label, "digest-%d" % index,
                                        synthetic.occluded_small(),
                                        origin="replacement"))

    assert store.flush() is True
    assert store.count() == 3
    assert [row["round_id"] for row in store.rows(limit=2, offset=0)] == [
        created[2].round_id, created[1].round_id]
    assert [row["round_id"] for row in store.rows(limit=2, offset=2)] == [
        created[0].round_id]
    store.close()
