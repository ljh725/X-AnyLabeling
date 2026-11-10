"""Task 2.6 -- scope disclosure: partial scope, unknown origin, gaps, bad IDs.

Covers spec ``BASE-8`` (a rectangle-only ratio must disclose incomplete scope),
``BASE-2`` (legacy/unknown origin never invents an AI count), ``REP-2.2``
(a recorded gap makes the row incomparable instead of silently complete) and
``BASE-1`` (duplicate identity or broken geometry nullifies identity-based
metrics rather than guessing).
"""

from __future__ import annotations

import pytest

from anylabeling.services.correction_metrics.core import SHAPE_ID

from . import synthetic

UNTRUSTED_FIELDS = ("added", "deleted", "geometry_changed", "class_changed",
                    "modified_original", "unchanged", "modified_rate",
                    "unchanged_rate")


def test_mixed_shapes_disclose_partial_scope_and_unsupported_count():
    """验证 BASE-8.3/REP-2.2：混合非矩形时披露 partial-scope 与 unsupported_count。"""
    round_obj = synthetic.make_round(synthetic.mixed_shapes())

    row = round_obj.row(draft=True)

    assert row["baseline_count"] == 8
    assert row["final_count"] == 8
    assert row["unsupported_count"] == 4
    assert "partial-scope" in row["issues"]
    assert row["comparable"] is False


def test_rectangle_to_polygon_conversion_is_a_scope_change():
    """验证 BASE-8.3：矩形转多边形产生 type-conversion + scope_changes，且不冒充增删。"""
    baseline = synthetic.mixed_shapes()
    shape = synthetic.by_id(baseline)["r-004"]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(
        shapes=[synthetic.polygon("r-004", shape["label"],
                                  [(80, 160), (140, 160), (110, 220)])],
        transaction_id="convert-1",
    ) is True

    row = round_obj.row(draft=True)
    assert row["scope_changes"] == 1
    assert row["added"] == 0
    assert row["deleted"] == 0
    assert row["baseline_count"] == 8
    assert row["final_count"] == 7
    assert row["unsupported_count"] == 5
    assert "type-conversion" in row["issues"]
    assert "partial-scope" in row["issues"]
    # The rectangle facts that are still comparable remain reported.
    assert row["modified_original"] == 0
    assert row["unchanged"] == 7
    assert row["transactions"] == 1


def test_unknown_origin_leaves_ai_count_unknown():
    """验证 BASE-2.1/REP-6.2：历史标注来源未知时 ai_count 为 None 并披露 unknown-origin。"""
    round_obj = synthetic.make_round(synthetic.unknown_origin(),
                                     origin="unknown-existing")

    row = round_obj.row(draft=True)

    assert row["ai_count"] is None
    assert "unknown-origin" in row["issues"]
    assert row["origin"] == "unknown-existing"
    # M1 修复：来源未知是披露项，不阻断本轮成本比较。
    assert row["comparable"] is True
    assert row["baseline_count"] == 25
    assert row["modified_rate"] == 0.0
    assert row["unchanged_rate"] == 1.0


def test_additive_origin_counts_only_the_ai_objects():
    """验证 BASE-3.1：追加预测起点里 ai_count 只数本次预测的 3 个对象，不是全部 8 个。"""
    round_obj = synthetic.make_round(
        synthetic.manual5_ai3(), origin="additive",
        predicted=("a-001", "a-002", "a-003"),
    )

    row = round_obj.row(draft=True)

    assert row["baseline_count"] == 8
    assert row["ai_count"] == 3
    assert row["origin"] == "additive"
    assert row["issues"] == []
    assert row["comparable"] is True


def test_recorded_gap_makes_the_row_incomparable():
    """验证 REP-2.2：记录存储缺口后该轮 comparable=False 且 issue 传播到行。"""
    round_obj = synthetic.make_round(synthetic.dense_30())

    round_obj.mark_gap("storage-gap")
    round_obj.mark_gap("storage-gap")

    row = round_obj.row(draft=True)
    assert "storage-gap" in row["issues"]
    assert row["issues"].count("storage-gap") == 1
    assert row["comparable"] is False
    # Counts are still readable, only completeness is denied.
    assert row["baseline_count"] == 30
    assert row["unchanged"] == 30


def test_duplicate_shape_ids_nullify_identity_metrics():
    """验证 BASE-1：重复对象 ID 产生 shape-identity-conflict 并把身份类净值置 None。"""
    shapes = [
        synthetic.rect("u-001", "cat", (20, 20, 90, 110)),
        synthetic.rect("u-001", "dog", (200, 20, 270, 110)),
    ]
    round_obj = synthetic.make_round(shapes, origin="unknown-existing")

    row = round_obj.row(draft=True)

    assert "shape-identity-conflict" in row["issues"]
    assert row["comparable"] is False
    assert row["baseline_count"] == 2
    assert row["final_count"] == 2
    for field in UNTRUSTED_FIELDS:
        assert row[field] is None, field
    assert {entry["kind"] for entry in row["classes"]} <= {"initial", "final"}


def test_invalid_geometry_nullifies_identity_metrics():
    """验证 BASE-1/REP-2.2：非法几何进入 invalid-geometry，身份类净值置 None 而非猜 0。"""
    shapes = [
        synthetic.rect("u-001", "cat", (20, 20, 90, 110)),
        synthetic.rect("u-002", "dog", (200, 20, 270, 110), points=[[200, 20]]),
    ]
    round_obj = synthetic.make_round(shapes, origin="unknown-existing")

    row = round_obj.row(draft=True)

    assert "invalid-geometry" in row["issues"]
    assert row["comparable"] is False
    assert row["baseline_count"] == 2
    for field in UNTRUSTED_FIELDS:
        assert row[field] is None, field


def test_unknown_origin_is_not_reported_for_known_prediction_origin():
    """验证 BASE-2：replacement 起点不产生 unknown-origin，ai_count 为可判定的 30。"""
    round_obj = synthetic.make_round(
        synthetic.dense_30(), origin="replacement",
        predicted=[shape[SHAPE_ID] for shape in synthetic.dense_30()],
    )

    row = round_obj.row(draft=True)

    assert row["ai_count"] == 30
    assert "unknown-origin" not in row["issues"]
    assert row["comparable"] is True


def test_partial_scope_issue_is_not_lost_after_a_rect_only_edit():
    """验证 BASE-8：混合场景中只编辑矩形不会把 partial-scope 洗成完整统计。"""
    baseline = synthetic.mixed_shapes()
    shape = synthetic.by_id(baseline)["r-001"]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(shapes=[synthetic.moved(shape, 4, 0)],
                           transaction_id="rect-edit") is True

    row = round_obj.row(draft=True)
    assert row["unsupported_count"] == 4
    assert "partial-scope" in row["issues"]
    assert row["comparable"] is False
    assert row["geometry_changed"] == 1
    assert row["unchanged"] == 7
