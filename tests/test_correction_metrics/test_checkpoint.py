"""Tasks 3.4-3.5 -- save checkpoints, save failure, save-as forking and
recovery of an interrupted session.

Covers spec ``STO-4`` (a saved revision and the draft stay in sync), ``STO-5``
(a failed save keeps the last saved version and the draft process), ``STO-6``
(save-as forks a new round without touching the old one), ``BASE-8.1``
(unobserved content or an external annotation change is disclosed as a gap,
never presented as a complete comparison) and ``TIM-8`` (an unclosed session
is marked ``interrupted-time``).
"""

from __future__ import annotations

import pytest

from anylabeling.services.correction_metrics.storage import MetricsStore

from . import synthetic

DB_NAME = "metrics.sqlite"


def image_pair(tmp_path):
    """Return stable image/label paths inside the test's temp directory."""
    return (str(tmp_path / "images" / "scene.png"),
            str(tmp_path / "labels" / "scene.json"))


def open_store(tmp_path, **kwargs):
    """Open a healthy ``MetricsStore`` or fail loudly with its error message."""
    store = MetricsStore(tmp_path / DB_NAME, dataset_id="ds-checkpoint", **kwargs)
    assert store.error is None, store.error
    return store


def revision_fields_match(draft_row, saved_row):
    """True when every net-cost field is identical in both views."""
    fields = ("added", "deleted", "geometry_changed", "class_changed",
              "modified_original", "unchanged", "modified_rate", "unchanged_rate")
    return all(draft_row[field] == saved_row[field] for field in fields)


def test_saved_advances_revision_and_matches_the_draft(tmp_path):
    """验证 STO-4：prepare_save()→saved() 推进 revision，且已保存视图与草稿视图一致。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    baseline_revision = round_obj.saved_revision
    shape = synthetic.by_id(baseline)["o-001"]

    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    assert token["digest"] != baseline_revision
    assert round_obj.saved(token) is True

    assert round_obj.saved_revision == token["digest"]
    assert round_obj.dirty is False
    assert store.flush() is True
    draft_row, saved_row = round_obj.row(draft=True), round_obj.row(draft=False)
    assert revision_fields_match(draft_row, saved_row)
    assert saved_row["geometry_changed"] == 1
    assert saved_row["is_draft"] is False
    store.close()


def test_failed_save_keeps_saved_revision_and_draft_process(tmp_path):
    """验证 STO-5：save_failed() 后已保存版本不变、草稿过程保留、token 失效。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    baseline_revision = round_obj.saved_revision
    shape = synthetic.by_id(baseline)["o-001"]

    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    round_obj.save_failed(token)

    assert round_obj.saved_revision == baseline_revision
    assert round_obj.dirty is True
    assert round_obj.saved(token) is False
    draft_row = round_obj.row(draft=True)
    saved_row = round_obj.row(draft=False)
    assert draft_row["geometry_changed"] == 1
    assert draft_row["is_draft"] is True
    assert saved_row["geometry_changed"] == 0
    store.close()


def test_save_as_forks_a_new_round_and_keeps_the_old_one(tmp_path):
    """验证 STO-6：保存到不同路径分叉出新轮次，旧轮次的已保存版本不受影响。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    other_label = str(tmp_path / "labels" / "copy.json")
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    baseline_revision = round_obj.saved_revision
    shape = synthetic.by_id(baseline)["o-001"]

    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj),
                                   label_path=other_label)
    assert round_obj.saved(token) is True

    assert round_obj.saved_revision == baseline_revision
    assert store.flush() is True
    assert store.count() == 2
    forked = store.latest(image, other_label)
    assert forked is not None
    assert forked.round_id != round_obj.round_id
    assert forked.saved_revision == token["digest"]
    assert store.open_existing(round_obj.round_id) is not None
    store.close()


def test_unobserved_content_change_is_flagged(tmp_path):
    """验证 BASE-8.1：prepare_save() 收到与草稿不一致的内容时披露 unobserved-content-change。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    extra = baseline + [synthetic.rect("n-001", "cat", (400, 400, 460, 460))]

    token = round_obj.prepare_save(extra)

    assert token["digest"] is not None
    row = round_obj.row(draft=True)
    assert "unobserved-content-change" in row["issues"]
    assert row["comparable"] is False
    # The checkpoint is still recorded for the caller to save.
    assert round_obj.saved(token) is True
    store.close()


def test_reopening_with_a_matching_pending_checkpoint_restores_saved_state(tmp_path):
    """验证 STO-4：重开时磁盘内容与 pending 检查点一致 → 恢复为已保存、不记缺口。"""
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    shape = synthetic.by_id(baseline)["o-001"]

    store = open_store(tmp_path)
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    draft = synthetic.draft_snapshot(round_obj)
    assert store.flush() is True
    store.close()

    reopened_store = open_store(tmp_path)
    reopened = reopened_store.open_round(image, label, "digest-a", draft,
                                         origin="replacement")
    assert reopened.round_id == round_obj.round_id
    assert reopened_store.flush() is True
    assert reopened.saved_revision == token["digest"]
    assert reopened.dirty is False
    assert "interrupted-draft" not in reopened.row(draft=True)["issues"]
    reopened_store.close()


def test_reopening_against_a_changed_file_flags_external_annotation_change(tmp_path):
    """验证 BASE-8.1：重开时标注文件与已知版本不同 → external-annotation-change，不冒充完整。"""
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    shape = synthetic.by_id(baseline)["o-001"]
    changed = [item for item in baseline if item[synthetic.SHAPE_ID] != "o-001"]

    store = open_store(tmp_path)
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    baseline_revision = round_obj.saved_revision
    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    assert store.flush() is True
    store.close()

    reopened_store = open_store(tmp_path)
    reopened = reopened_store.open_round(image, label, "digest-a", changed,
                                         origin="replacement")
    assert reopened.round_id == round_obj.round_id
    assert reopened_store.flush() is True
    row = reopened.row(draft=True)
    assert "external-annotation-change" in row["issues"]
    assert row["comparable"] is False
    assert row["deleted"] == 1
    assert reopened.completed is False
    assert reopened.saved_revision == baseline_revision
    reopened_store.close()


def test_changed_image_digest_starts_a_new_round_and_flags_it(tmp_path):
    """验证 BASE-1：同一路径但图片内容变化 → 新轮次 + image-content-changed，旧轮次保留。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()

    first = store.open_round(image, label, "digest-a", baseline,
                             origin="replacement")
    second = store.open_round(image, label, "digest-b", baseline,
                              origin="replacement")

    assert second.round_id != first.round_id
    assert "image-content-changed" in second.row(draft=True)["issues"]
    assert second.row(draft=True)["comparable"] is False
    assert store.flush() is True
    assert store.count() == 2
    assert store.open_existing(first.round_id) is not None
    store.close()


def test_unclosed_session_is_marked_interrupted_time(tmp_path):
    """验证 TIM-8：上次未闭合的计时会话在重开时被标记 interrupted-time，时长仍保留。"""
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()

    store = open_store(tmp_path)
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    round_obj.set_time("session-A", {"total": 12.5}, closed=False)
    assert store.flush() is True
    store.close()

    reopened_store = open_store(tmp_path)
    reopened = reopened_store.open_round(image, label, "digest-a", baseline,
                                         origin="replacement")
    row = reopened.row(draft=True)
    assert "interrupted-time" in row["issues"]
    assert row["comparable"] is False
    assert row["time"] == {"total": 12.5}
    reopened_store.close()


def test_finish_requires_a_clean_saved_round(tmp_path):
    """验证 EVT-8/STO-4：有未保存改动或待定检查点的轮次不能完成，干净轮次可完成且幂等。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    shape = synthetic.by_id(baseline)["o-001"]

    assert round_obj.finish() is True
    assert round_obj.completed is True
    assert round_obj.finish() is True

    assert round_obj.resume() is True
    assert round_obj.completed is False
    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    assert round_obj.finish() is False

    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))
    assert round_obj.finish() is False
    assert round_obj.saved(token) is True
    assert round_obj.finish() is True
    store.close()


def test_saved_rejects_a_foreign_or_stale_token(tmp_path):
    """验证 STO-4/STO-6：其他轮次或已失效的 token 不能把当前草稿标记为已保存。"""
    store = open_store(tmp_path)
    image, label = image_pair(tmp_path)
    baseline = synthetic.occluded_small()
    round_obj = store.open_round(image, label, "digest-a", baseline,
                                 origin="replacement")
    shape = synthetic.by_id(baseline)["o-001"]

    assert round_obj.patch(shapes=[synthetic.moved(shape, 2, 2)],
                           transaction_id="tx-1") is True
    token = round_obj.prepare_save(synthetic.draft_snapshot(round_obj))

    assert round_obj.saved(dict(token, round_id="not-this-round")) is False
    assert round_obj.saved(dict(token, id="stale-token")) is False
    assert round_obj.saved(None) is False
    assert round_obj.dirty is True

    assert round_obj.saved(token) is True
    assert round_obj.dirty is False
    store.close()


# ---------------------------------------------------------------------------
# Task 5.1 -- repeated autosaves confirm one revision, never double-count
# ---------------------------------------------------------------------------
def test_repeated_autosaves_keep_one_transaction_and_the_process_cost():
    """5.1：连续自动保存只确认最新快照，不重复计数、不清空过程成本。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)
    moved = synthetic.moved(synthetic.by_id(baseline)["p-001"], 5, 5)
    current = [moved if shape["xanylabeling_shape_id"] == "p-001" else shape
               for shape in baseline]

    assert round_obj.patch(shapes=[moved], transaction_id="T1") is True
    round_obj.set_time("session-1", {"working": 12.0})

    revisions = []
    for _ in range(3):
        token = round_obj.prepare_save(current)
        assert round_obj.saved(token) is True
        revisions.append(round_obj.row()["revision"])
        row = round_obj.row()
        assert row["transactions"] == 1
        assert row["touches"] == 1
        assert row["geometry_changed"] == 1
        assert row["time"]["working"] == 12.0

    assert len(set(revisions)) == 1
    assert round_obj.row(draft=True)["is_draft"] is False


def test_an_autosave_that_fails_keeps_the_previous_saved_revision():
    """5.1：保存失败保持草稿与上一次成功 revision，不推进已保存结果。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)
    first = round_obj.prepare_save(baseline)
    assert round_obj.saved(first) is True
    saved_revision = round_obj.row()["revision"]

    moved = synthetic.moved(synthetic.by_id(baseline)["p-002"], 9, 9)
    assert round_obj.patch(shapes=[moved], transaction_id="T2") is True
    failing = round_obj.prepare_save(
        [moved if shape["xanylabeling_shape_id"] == "p-002" else shape
         for shape in baseline]
    )
    round_obj.save_failed(failing)

    row = round_obj.row(draft=True)
    assert row["revision"] == saved_revision
    assert row["is_draft"] is True
    assert row["transactions"] == 1
