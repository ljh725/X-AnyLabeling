"""Task 2.5 -- taxonomy migration must not be charged as a personal relabel.

Covers spec ``EVT-7`` (class changes are judged after the explicit class
mapping), ``BASE-5`` (a class-system migration is not a correction) and
``REP-2/REP-6`` (an incomparable class system leaves the class dimension N/A
while rectangle facts stay readable).
"""

from __future__ import annotations

import pytest

from anylabeling.services.correction_metrics.core import SHAPE_ID, differences, snapshot

from . import synthetic

RENAME = {"cat": "feline", "dog": "canine", "person": "human",
          "car": "vehicle", "tree": "plant", "sign": "marker"}


def test_one_to_one_rename_creates_no_personal_class_change():
    """验证 EVT-7：一对一类别重命名后 class_changed=0、可比较性保持、不产生事务。"""
    round_obj = synthetic.make_round(synthetic.dense_30())

    assert round_obj.taxonomy(RENAME) is True

    row = round_obj.row(draft=True)
    assert row["class_changed"] == 0
    assert row["geometry_changed"] == 0
    assert row["modified_original"] == 0
    assert row["unchanged"] == 30
    assert row["transactions"] == 0
    assert row["touches"] == 0
    assert row["unique_objects"] == 0
    assert row["comparable"] is True
    assert "class-incomparable" not in row["issues"]
    # The six labels are still six distinct classes after a 1:1 rename.
    assert len(set(RENAME.values())) == 6


def test_personal_relabel_before_rename_is_preserved():
    """验证 EVT-7：重命名前的个人改类历史在映射后仍然只算 1 次真实改类。"""
    baseline = synthetic.dense_30()
    shape = synthetic.by_id(baseline)["p-002"]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(shapes=[synthetic.relabelled(shape, "dog")],
                           transaction_id="personal-relabel") is True
    assert round_obj.taxonomy(RENAME) is True

    row = round_obj.row(draft=True)
    assert row["class_changed"] == 1
    assert row["geometry_changed"] == 0
    assert row["modified_original"] == 1
    assert row["unchanged"] == 29
    assert row["transactions"] == 1
    assert row["comparable"] is True


def test_merge_marks_the_class_dimension_unavailable():
    """验证 BASE-5/REP-2.2：多对一合并后类别维度不可比，class 字段为 None 而几何仍可算。"""
    baseline = synthetic.dense_30()
    shape = synthetic.by_id(baseline)["p-003"]
    round_obj = synthetic.make_round(baseline)

    assert round_obj.patch(shapes=[synthetic.moved(shape, 6, 4)],
                           transaction_id="move-before-merge") is True
    assert round_obj.taxonomy({"cat": "animal", "dog": "animal", "person": "animal"},
                              comparable=True) is True

    row = round_obj.row(draft=True)
    assert row["class_changed"] is None
    assert row["modified_original"] is None
    assert row["unchanged"] is None
    assert row["modified_rate"] is None
    assert row["unchanged_rate"] is None
    # Geometry facts survive the incomparable class system.
    assert row["geometry_changed"] == 1
    assert row["added"] == 0
    assert row["deleted"] == 0
    assert row["baseline_count"] == 30
    assert row["final_count"] == 30
    assert row["comparable"] is False
    assert "class-incomparable" in row["issues"]


def test_incomparable_classes_still_report_zero_denominator_as_na():
    """验证 REP-6.2：分母为零且类别不可比时所有比例字段仍为 None（不是 0）。"""
    net = differences(snapshot(synthetic.empty_scene()),
                      snapshot([synthetic.rect("n-001", "cat", (10, 10, 50, 50))]),
                      class_comparable=False)

    assert net["baseline_count"] == 0
    assert net["added"] == 1
    assert net["class_changed"] is None
    assert net["modified_original"] is None
    assert net["unchanged"] is None
    assert net["modified_rate"] is None
    assert net["unchanged_rate"] is None


def test_taxonomy_mapping_keeps_other_classes_untouched():
    """验证 EVT-7：映射只影响被点名的类别，未映射类别的身份仍是 unchanged。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)

    assert round_obj.taxonomy({"cat": "feline"}) is True

    row = round_obj.row(draft=True)
    assert row["class_changed"] == 0
    assert row["unchanged"] == 30
    assert row["modified_rate"] == 0.0


def test_taxonomy_with_no_effective_change_records_nothing():
    """验证 EVT-1.2：类别映射与现有标签一致时不产生事务、不改动净值。"""
    round_obj = synthetic.make_round(synthetic.dense_30())

    assert round_obj.taxonomy({"cat": "cat", "dog": "dog"}) is False

    row = round_obj.row(draft=True)
    assert row["transactions"] == 0
    assert row["touches"] == 0
    assert row["unchanged"] == 30


def test_rename_does_not_change_the_class_counts_rows():
    """验证 EVT-7.1：重命名后 classes 行仍按映射后的类别统计，不会出现虚假改类行。"""
    baseline = synthetic.dense_30()
    round_obj = synthetic.make_round(baseline)
    assert round_obj.taxonomy(RENAME) is True

    net = differences(snapshot(baseline), synthetic.draft_snapshot(round_obj),
                      RENAME, True)

    assert net["class_changed"] == 0
    class_rows = [row for row in net["classes"] if row["kind"] == "class_changed"]
    assert class_rows == []
    initial = {row["initial_class"]: row["count"]
               for row in net["classes"] if row["kind"] == "initial"}
    assert initial == {"cat": 5, "dog": 5, "person": 5,
                       "car": 5, "tree": 5, "sign": 5}


# ---------------------------------------------------------------------------
# Task 2.5 -- explicit, versioned class-vocabulary mappings
# ---------------------------------------------------------------------------
def test_a_confirmed_rename_appends_one_versioned_mapping():
    """2.5：确认的一对一改名生成新的类别体系版本并保留映射内容。"""
    round_obj = synthetic.make_round(synthetic.dense_30())
    assert round_obj.row(draft=True)["class_version"] == 1
    assert round_obj.row(draft=True)["category_version"] is None

    assert round_obj.taxonomy(RENAME) is True

    row = round_obj.row(draft=True)
    assert row["class_version"] == 2
    assert row["category_version"] == "local-v2"
    assert len(row["class_migrations"]) == 1
    record = row["class_migrations"][0]
    assert record["previous"] == 1
    assert record["version"] == 2
    assert record["mapping"] == RENAME
    assert record["comparable"] is True

    # Repeating the identical declaration is idempotent: no phantom v3.
    assert round_obj.taxonomy(RENAME) is False
    assert round_obj.row(draft=True)["class_version"] == 2


def test_an_identity_declaration_does_not_create_a_class_version():
    """2.5：未实际改名的映射不算体系迁移，不消耗版本号。"""
    round_obj = synthetic.make_round(synthetic.dense_30())

    assert round_obj.taxonomy({"cat": "cat", "dog": "dog"}) is False

    row = round_obj.row(draft=True)
    assert row["class_version"] == 1
    assert row["class_migrations"] == []
    assert row["category_version"] is None


def test_a_merge_is_versions_recorded_as_incomparable():
    """2.5：合并声明仍生成可追溯版本，但该版本标注为不可比。"""
    merge = {"cat": "animal", "dog": "animal", "person": "animal"}
    round_obj = synthetic.make_round(synthetic.dense_30())

    assert round_obj.taxonomy(merge) is True

    row = round_obj.row(draft=True)
    assert row["class_version"] == 2
    assert row["category_version"] == "local-v2"
    record = row["class_migrations"][-1]
    assert record["mapping"] == merge
    assert record["comparable"] is False
    assert "class-incomparable" in row["issues"]


def test_the_provenance_category_version_wins_over_the_local_label():
    """2.5：预测来源自带类别版本时保留它，不覆盖为本地 vN。"""
    round_obj = synthetic.make_round(
        synthetic.dense_30(),
        provenance={"category_version": "model-classes-42"},
    )

    assert round_obj.taxonomy({"cat": "feline"}) is True

    row = round_obj.row(draft=True)
    assert row["category_version"] == "model-classes-42"
    assert row["class_version"] == 2
