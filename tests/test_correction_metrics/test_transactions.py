"""Task 2.4 -- transaction accounting: one completed action, one transaction.

Covers spec ``EVT-1.1`` (many mouse events inside one drag still count once),
``EVT-1.2`` (a completed action without content change records nothing),
``EVT-2.1`` (one action touching several objects counts one transaction but
every touched object), ``EVT-2.2`` (repeated edits of one object), ``EVT-4``
(process cost survives when the net result returns to the baseline) and the
``transactions``/``touches``/``unique_objects`` split of
samples-design.md §2.
"""

from __future__ import annotations

from anylabeling.services.correction_metrics.core import SHAPE_ID

from . import synthetic


def test_one_transaction_with_several_objects_counts_once():
    """验证 EVT-2.1：一次事务改多个对象的多字段，只计 1 次事务但触达全部对象。"""
    baseline = synthetic.dense_30()
    shapes = synthetic.by_id(baseline)
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(
        shapes=[synthetic.relabelled(shapes["p-002"], "dog"),
                synthetic.moved(shapes["p-003"], 6, 4)],
        transaction_id="batch-1",
    ) is True

    row = round_obj.row(draft=True)
    assert row["transactions"] == 1
    assert row["touches"] == 2
    assert row["unique_objects"] == 2
    assert row["class_changed"] == 1
    assert row["geometry_changed"] == 1
    assert row["modified_original"] == 2
    assert row["operation_counts"] == {"edit": 1}


def test_repeated_transaction_id_is_idempotent():
    """验证 EVT-1.1：同一 transaction_id 重复提交返回 False，只记录一次事务。"""
    baseline = synthetic.dense_30()
    shape = synthetic.by_id(baseline)["p-003"]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(shapes=[synthetic.moved(shape, 6, 4)],
                           transaction_id="drag-1") is True
    assert round_obj.patch(shapes=[synthetic.moved(shape, 12, 8)],
                           transaction_id="drag-1") is False

    row = round_obj.row(draft=True)
    assert row["transactions"] == 1
    assert row["touches"] == 1
    assert row["unique_objects"] == 1
    # The rejected duplicate never reached the draft.
    assert row["geometry_changed"] == 1


def test_action_without_content_change_records_nothing():
    """验证 EVT-1.2：提交与草稿完全一致的内容不产生事务，也不增加触达。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)
    shape = synthetic.by_id(baseline)["p-003"]

    assert round_obj.patch(shapes=[shape], transaction_id="noop-1") is False
    assert round_obj.patch(shapes=[], transaction_id="noop-2") is False

    row = round_obj.row(draft=True)
    assert row["transactions"] == 0
    assert row["touches"] == 0
    assert row["unique_objects"] == 0
    assert row["operation_counts"] == {}
    assert row["modified_original"] == 0
    assert row["unchanged"] == 30


def test_create_then_delete_keeps_process_cost_with_zero_net():
    """验证 EVT-3.2/EVT-4：新增后再删除，净值归零但两次事务与触达仍保留。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(shapes=[synthetic.rect("n-101", "cat", (40, 560, 110, 620))],
                           transaction_id="create-1") is True
    assert round_obj.patch(removed_ids=("n-101",),
                           transaction_id="delete-1") is True

    row = round_obj.row(draft=True)
    assert row["baseline_count"] == 30
    assert row["final_count"] == 30
    assert row["added"] == 0
    assert row["deleted"] == 0
    assert row["modified_original"] == 0
    assert row["unchanged"] == 30
    assert row["transactions"] == 2
    assert row["touches"] == 2
    assert row["unique_objects"] == 1
    assert row["operation_counts"] == {"create": 1, "delete": 1}


def test_undo_back_to_start_zeroes_net_but_keeps_transaction_and_touches():
    """验证 EVT-4：改框后撤销回起点，净值归零但原事务与触达计数保留、撤销单列。"""
    baseline = synthetic.dense_30()
    shape = synthetic.by_id(baseline)["p-003"]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(shapes=[synthetic.moved(shape, 6, 4)],
                           transaction_id="move-1") is True
    assert round_obj.patch(shapes=[shape], kind="undo",
                           transaction_id="undo-1") is True

    row = round_obj.row(draft=True)
    assert row["baseline_count"] == 30
    assert row["final_count"] == 30
    assert row["geometry_changed"] == 0
    assert row["modified_original"] == 0
    assert row["unchanged"] == 30
    # The edit is still the one user transaction; undo is reported separately.
    assert row["transactions"] == 1
    assert row["undo_count"] == 1
    assert row["touches"] == 2
    assert row["unique_objects"] == 1
    assert row["operation_counts"] == {"geometry": 1, "undo": 1}


def test_touches_count_every_touch_while_unique_objects_deduplicate():
    """验证 EVT-2.2：11 次事务触达 13 次，但 p-014 只算 1 个唯一对象（12）。"""
    round_obj = synthetic.make_round(synthetic.dense_30())
    synthetic.apply_dense_script(round_obj)

    row = round_obj.row(draft=True)

    assert row["transactions"] == 11
    assert row["touches"] == 13
    assert row["unique_objects"] == 12
    assert row["operation_counts"] == {
        "create": 1, "delete": 1, "geometry": 5, "relabel": 4,
    }


def test_review_event_is_not_a_transaction():
    """验证 EVT-8/TIM：审核事件不计入 transactions，也不增加触达对象。"""
    round_obj = synthetic.make_round(synthetic.unknown_origin(),
                                     origin="unknown-existing")

    assert round_obj.review_event("review-confirm", ["u-001", "u-002"],
                                  transaction_id="review-1") is True
    assert round_obj.review_event("review-confirm", ["u-001"],
                                  transaction_id="review-1") is False

    row = round_obj.row(draft=True)
    assert row["transactions"] == 0
    assert row["touches"] == 0
    assert row["unique_objects"] == 0
    assert row["undo_count"] == 0
    assert row["operation_counts"] == {"review-confirm": 1}
    # Reviewing does not change any object.
    assert row["modified_original"] == 0
    assert row["unchanged"] == 25


def test_sync_records_one_transaction_for_the_whole_draft():
    """验证 EVT-1.1/EVT-2.1：sync 整份草稿只产生 1 次事务，且无变化时返回 False。"""
    baseline = synthetic.dense_30()
    shapes = synthetic.by_id(baseline)
    round_obj = synthetic.make_round(baseline)
    edited = [synthetic.moved(shapes["p-003"], 6, 4) if
              item[SHAPE_ID] == "p-003" else item for item in baseline]

    assert round_obj.sync(edited, transaction_id="sync-1") is True
    assert round_obj.sync(edited, transaction_id="sync-2") is False

    row = round_obj.row(draft=True)
    assert row["transactions"] == 1
    assert row["touches"] == 1
    assert row["unique_objects"] == 1
    assert row["geometry_changed"] == 1
    assert row["unchanged"] == 29


def test_batch_relabel_of_ten_objects_is_one_transaction():
    """验证 EVT-2.1：批量改类 10 个对象 = 1 事务 / 10 触达 / 10 唯一对象。"""
    baseline = synthetic.stress_300()
    relabelled = [synthetic.relabelled(shape, "sign") if
                  int(shape[SHAPE_ID].split("-")[1]) <= 10 else shape
                  for shape in baseline]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.sync(relabelled, transaction_id="batch-relabel") is True

    row = round_obj.row(draft=True)
    assert row["transactions"] == 1
    assert row["touches"] == 10
    assert row["unique_objects"] == 10
    assert row["class_changed"] == 10
    assert row["modified_original"] == 10
    assert row["unchanged"] == 290
    assert row["modified_rate"] == 1 / 30
    assert row["unchanged_rate"] == 29 / 30
