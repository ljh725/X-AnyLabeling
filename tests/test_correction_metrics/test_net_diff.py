"""Task 2.3 -- snapshot normalisation and net correction difference.

Covers spec ``EVT-3`` (net result is computed on stable identities and
normalised geometry), ``EVT-7`` (rates against the baseline denominator, N/A
instead of division by zero), ``BASE-8`` (non-rectangles stay out of the
rectangle numerator/denominator but are disclosed as unsupported) and
``REP-2`` (empty baseline reports N/A, never 0).
"""

from __future__ import annotations

import pytest

from anylabeling.services.correction_metrics.core import SHAPE_ID, differences, snapshot

from . import synthetic


def test_rectangle_points_are_normalised_to_min_max_bounds():
    """验证 EVT-3：矩形无论点序/起点如何，快照都归一化为 [minx,miny,maxx,maxy]。"""
    scrambled = synthetic.rect("p-001", "cat", (20, 20, 90, 110),
                              points=[[90, 110], [20, 110], [90, 20], [20, 20]])
    two_points = synthetic.rect("p-002", "dog", (20, 20, 90, 110),
                                points=[[90, 110], [20, 20]])

    data = snapshot([scrambled, two_points])

    assert data["objects"]["p-001"]["geometry"] == [20.0, 20.0, 90.0, 110.0]
    assert data["objects"]["p-002"]["geometry"] == [20.0, 20.0, 90.0, 110.0]
    assert data["issues"] == []


def test_int_and_float_coordinates_are_the_same_geometry():
    """验证 EVT-3：整数与浮点坐标表示同一矩形，不算改框。"""
    integer_box = synthetic.rect("p-001", "cat", (20, 20, 90, 110))
    float_box = synthetic.rect("p-001", "cat", (0, 0, 0, 0),
                               points=[[20.0, 20.0], [90.0, 20.0],
                                       [90.0, 110.0], [20.0, 110.0]])

    net = differences(snapshot([integer_box]), snapshot([float_box]))

    assert net["baseline_count"] == 1
    assert net["final_count"] == 1
    assert net["geometry_changed"] == 0
    assert net["modified_original"] == 0
    assert net["unchanged"] == 1
    assert net["unchanged_rate"] == 1.0


def test_reordered_shape_list_is_not_a_correction():
    """验证 BASE-1.1：对象顺序重排不产生任何修正（身份集合比较）。"""
    baseline = synthetic.dense_30()
    reordered = list(reversed(baseline))

    net = differences(snapshot(baseline), snapshot(reordered))

    assert net["baseline_count"] == 30
    assert net["final_count"] == 30
    assert (net["added"], net["deleted"], net["geometry_changed"],
            net["class_changed"], net["modified_original"]) == (0, 0, 0, 0, 0)
    assert net["unchanged"] == 30
    assert net["modified_rate"] == 0.0
    assert net["unchanged_rate"] == 1.0


def test_dense_30_scripted_corrections_net_result():
    """验证 EVT-2.2/EVT-3.1/EVT-3.2：30 框脚本化修正的净结果为 10 改 / 20 未改。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)
    synthetic.apply_dense_script(round_obj)

    row = round_obj.row(draft=True)

    assert row["baseline_count"] == 30
    assert row["final_count"] == 30
    assert row["added"] == 2
    assert row["deleted"] == 2
    assert row["geometry_changed"] == 5
    assert row["class_changed"] == 4
    # p-014 changed both geometry and class but counts once as an original box.
    assert row["modified_original"] == 10
    assert row["unchanged"] == 20
    assert row["modified_rate"] == pytest.approx(1 / 3)
    assert row["unchanged_rate"] == pytest.approx(2 / 3)


def test_modified_original_deduplicates_one_object_changed_twice():
    """验证 EVT-3.1：同一原框既改类又改框时 modified_original 只 +1。"""
    baseline = synthetic.dense_30()
    shape = synthetic.by_id(baseline)["p-014"]
    both = synthetic.relabelled(synthetic.moved(shape, 6, 4), "dog")

    net = differences(snapshot(baseline), snapshot(
        [both if s[SHAPE_ID] == "p-014" else s for s in baseline]))

    assert net["geometry_changed"] == 1
    assert net["class_changed"] == 1
    assert net["modified_original"] == 1
    assert net["unchanged"] == 29


def test_untouched_scene_reports_every_object_unchanged():
    """验证 EVT-1.2：没有任何变化时 modified 为 0、unchanged 覆盖全部基线框。"""
    baseline = synthetic.dense_30()

    net = differences(snapshot(baseline), snapshot(synthetic.dense_30()))

    assert net["modified_original"] == 0
    assert net["unchanged"] == 30
    assert net["modified_rate"] == 0.0
    assert net["unchanged_rate"] == 1.0
    assert net["added"] == 0
    assert net["deleted"] == 0


def test_half_pixel_geometry_change_is_detected():
    """验证 EVT-3：0.5px 级真实微调必须被识别为改框（亚像素不能被吞掉）。"""
    baseline = synthetic.occluded_small()
    edited = []
    for shape in baseline:
        if shape[SHAPE_ID] == "o-005":
            left, top, right, bottom = synthetic.bbox_of(shape)
            shape = synthetic.rect("o-005", shape["label"],
                                   (left, top, right + 0.5, bottom))
        edited.append(shape)

    net = differences(snapshot(baseline), snapshot(edited))

    assert net["geometry_changed"] == 1
    assert net["modified_original"] == 1
    assert net["unchanged"] == 11
    assert net["modified_rate"] == pytest.approx(1 / 12)


def test_equivalent_rewrite_of_points_is_not_a_geometry_change():
    """验证 EVT-3：四点逆序、两点对角线、整数改浮点等重写不算改框。"""
    baseline = synthetic.occluded_small()
    rewritten = []
    for shape in baseline:
        left, top, right, bottom = synthetic.bbox_of(shape)
        if shape[SHAPE_ID] in ("o-001", "o-002", "o-003"):
            points = [[right, bottom], [left, bottom], [left, top], [right, top]]
        elif shape[SHAPE_ID] in ("o-004", "o-005"):
            points = [[right, bottom], [left, top]]
        elif shape[SHAPE_ID] == "o-007":
            points = [[float(left), float(top)], [float(right), float(top)],
                      [float(right), float(bottom)], [float(left), float(bottom)]]
        else:
            points = [list(p) for p in shape["points"]]
        rewritten.append(synthetic.rect(shape[SHAPE_ID], shape["label"], (0, 0, 0, 0),
                                        points=points))

    net = differences(snapshot(baseline), snapshot(rewritten))

    assert net["geometry_changed"] == 0
    assert net["modified_original"] == 0
    assert net["unchanged"] == 12


def test_empty_baseline_reports_na_rates_instead_of_zero():
    """验证 REP-6.2/EVT-7.2：空起点新增 3 框时比例字段为 None（N/A）而非 0 或除零。"""
    net = differences(snapshot(synthetic.empty_scene()),
                      snapshot([synthetic.rect("n-%03d" % i, "cat",
                                               (10 * i, 10, 10 * i + 20, 30))
                                for i in (1, 2, 3)]))

    assert net["baseline_count"] == 0
    assert net["final_count"] == 3
    assert net["added"] == 3
    assert net["deleted"] == 0
    assert net["modified_original"] == 0
    assert net["unchanged"] == 0
    assert net["modified_rate"] is None
    assert net["unchanged_rate"] is None


def test_non_rectangles_are_excluded_but_reported_as_unsupported():
    """验证 BASE-8.3：非矩形不计入基线/终态矩形数，而以 unsupported_count 披露。"""
    shapes = synthetic.mixed_shapes()

    net = differences(snapshot(shapes), snapshot(shapes))

    assert len(shapes) == 12
    assert net["baseline_count"] == 8
    assert net["final_count"] == 8
    assert net["unsupported_count"] == 4
    assert net["added"] == 0
    assert net["deleted"] == 0
    assert net["geometry_changed"] == 0
    assert net["unchanged"] == 8


def test_rectangle_to_polygon_conversion_is_not_added_or_deleted():
    """验证 BASE-8.3：矩形转多边形（ID 不变）既不算新增也不算删除，单列 scope_changes。"""
    baseline = synthetic.mixed_shapes()
    converted = []
    for shape in baseline:
        if shape[SHAPE_ID] == "r-004":
            shape = synthetic.polygon("r-004", shape["label"],
                                      [(80, 160), (140, 160), (110, 220)])
        converted.append(shape)

    net = differences(snapshot(baseline), snapshot(converted))

    assert net["baseline_count"] == 8
    assert net["final_count"] == 7
    assert net["added"] == 0
    assert net["deleted"] == 0
    assert net["scope_changes"] == 1
    assert net["unsupported_count"] == 5


def test_class_changed_counts_only_relabelled_common_objects():
    """验证 EVT-7.1：仅改类的方向可由 classes 行读出，几何变化不混入改类。"""
    baseline = synthetic.dense_30()
    shapes = synthetic.by_id(baseline)
    edited = [synthetic.relabelled(shapes["p-002"], "dog") if
              s[SHAPE_ID] == "p-002" else s for s in baseline]

    net = differences(snapshot(baseline), snapshot(edited))
    rows = [row for row in net["classes"] if row["kind"] == "class_changed"]

    assert net["class_changed"] == 1
    assert net["geometry_changed"] == 0
    assert rows == [{"kind": "class_changed", "initial_class": "cat",
                     "final_class": "dog", "count": 1, "denominator": 5}]
