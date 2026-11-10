"""Regression tests for batch-1 audit defects M1, M3 and M4.

M1 -- ``unknown-origin`` is a disclosure, not a completeness blocker
      (baseline spec BASE-2.1 "已有标注起点明确声明来源"; events spec only lets
      scope/type-conversion/log-timing gaps invalidate a full comparison).
M3 -- a failed prediction record must leave a *visible* gap on the affected
      image instead of disappearing into an unattributed bucket
      (baseline spec BASE-4 "单张与批量预测建立同等可追溯记录").
M4 -- class rows use N/A denominators when the baseline is empty
      (baseline spec BASE-6 "分母为零时输出 N/A 而非零或无穷").

The tests are pure service-level regressions; they do not need Qt.
"""

from __future__ import annotations

from anylabeling.services.correction_metrics import reporting
from anylabeling.services.correction_metrics.core import differences, snapshot
from anylabeling.services.correction_metrics.storage import MetricsStore

from . import synthetic


def test_unknown_origin_round_stays_comparable():
    """验证 BASE-2.1：历史标注轮次只披露 unknown-origin，不因来源未知而失去可比性。"""
    round_obj = synthetic.make_round(synthetic.unknown_origin(),
                                     origin="unknown-existing")

    row = round_obj.row(draft=True)

    assert "unknown-origin" in row["issues"]
    assert row["comparable"] is True


def test_outcome_counts_a_round_that_only_discloses_unknown_origin():
    """验证 REP-2：汇总的完成/可比计数不排除只带来源披露的轮次。"""
    round_obj = synthetic.make_round(synthetic.unknown_origin(),
                                     origin="unknown-existing")
    row = dict(round_obj.row(), completed=True, current=True)

    completed, comparable, excluded = reporting.outcome([row])

    assert (completed, comparable) == (1, 1)
    assert dict(excluded) == {}


def test_density_groups_keep_disclosure_only_rounds():
    """验证 REP-5.1：按目标数量分组不因 unknown-origin 丢失轮次。"""
    round_obj = synthetic.make_round(synthetic.unknown_origin(),
                                     origin="unknown-existing")
    row = dict(round_obj.row(), completed=True, current=True)

    groups = reporting.density_groups([row])

    assert sum(group["rounds"] for group in groups) == 1


def test_scope_gap_is_still_a_blocking_reason():
    """验证 BASE-8.3：真正的范围缺口（partial-scope）仍然阻断完整比较。"""
    round_obj = synthetic.make_round(synthetic.mixed_shapes())

    row = round_obj.row(draft=True)

    assert "partial-scope" in row["issues"]
    assert row["comparable"] is False
    assert "partial-scope" in reporting.exclusion_reasons(row)


def test_empty_baseline_class_rows_report_na_denominators():
    """验证 BASE-6/REP-6.2：B 为空时类别明细的分母是 N/A 而不是 0。"""
    net = differences(snapshot(synthetic.empty_scene()),
                      snapshot([synthetic.rect("n-001", "cat", (10, 10, 50, 50))]))

    assert net["baseline_count"] == 0
    assert net["added"] == 1
    kinds = {row["kind"] for row in net["classes"]}
    assert kinds == {"added", "final"}
    assert [row["denominator"] for row in net["classes"]] == [None, None]


def test_failed_prediction_record_leaves_a_visible_gap(tmp_path):
    """验证 BASE-4：预测记录写入失败必须在该图片的轮次上显示预测缺口。"""
    store = MetricsStore(str(tmp_path / "metrics.sqlite3"))
    round_obj = store.open_round("scene.png", "scene.json", "image-digest-1",
                                 synthetic.dense_30())
    assert store.flush() is True
    store.close()

    assert store.record_prediction(
        "scene.png", "scene.json", {"model": "m1"}, "applied") is None

    assert "prediction-gap" in store.gaps_for("scene.png", "scene.json")
    row = round_obj.row()
    assert "prediction-gap" in row["issues"]
    assert row["comparable"] is False


def test_unsaved_round_reports_no_final_count():
    """验证 BASE-7：没有成功保存版本时不输出看似真实的最终计数。"""
    round_obj = synthetic.make_round(synthetic.dense_30(), saved=False)

    row = round_obj.row()

    assert row["final_count"] is None
    assert row["unsupported_count"] is None
    assert row["scope_changes"] is None
    assert row["comparable"] is False
