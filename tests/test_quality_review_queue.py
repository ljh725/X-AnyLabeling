"""Quality review queue model tests (tasks G1-G5, G7).

Covers: loading report.json, loading review.tsv, merging feedback,
writing feedback back to TSV, empty-decision exclusion from stats, and
rescan-preserves-feedback.

Run: pytest tests/test_quality_review_queue.py -v
"""

import csv
import json
import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    load_threshold_profile,
    run_quality_check,
    write_report_json,
    write_review_tsv,
)
from anylabeling.views.labeling.widgets.inspector.quality.quality_review_queue import (  # noqa: E402
    QualityReviewItem,
    QualityReviewQueue,
    STATUS_TO_FEEDBACK,
    status_from_decision,
)

# ---------------------------------------------------------------------------
# fixtures: build a real report + review.tsv via the checker
# ---------------------------------------------------------------------------


def _make_annotation(path):
    data = {
        "imagePath": "a.jpg",
        "imageWidth": 1000,
        "imageHeight": 1000,
        "shapes": [
            {
                "label": "person",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[100, 100], [400, 600]],
            },
            {
                "label": "head",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[150, 120], [210, 180]],
            },
            {
                "label": "face",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[140, 110], [260, 190]],
            },
        ],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


@pytest.fixture
def report_and_tsv(tmp_path):
    ann = tmp_path / "a.json"
    _make_annotation(str(ann))
    profile = load_threshold_profile()
    rep = run_quality_check(
        [str(ann)], profile=profile, input_root=str(tmp_path)
    )
    report_path = tmp_path / "report.json"
    tsv_path = tmp_path / "review.tsv"
    write_report_json(rep, str(report_path))
    write_review_tsv(rep, str(tsv_path))
    return str(report_path), str(tsv_path), rep


# ---------------------------------------------------------------------------
# G1 — load report.json
# ---------------------------------------------------------------------------


class TestLoadReport:
    def test_loads_all_issues(self, report_and_tsv):
        report_path, _, rep = report_and_tsv
        q = QualityReviewQueue()
        n = q.load_report(report_path)
        assert n == len(rep.issues)
        assert q.total == n
        assert q.run_id == rep.run_id

    def test_each_item_has_required_fields(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        for item in q.items():
            assert item.issue_id
            assert item.rule_name
            assert item.severity in ("error", "warning", "info")
            assert item.file_path
            assert item.status == "pending"
            assert item.decision == ""

    def test_primary_metric_carried_through(self, report_and_tsv):
        report_path, _, rep = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        # at least one L2 issue should carry a primary metric
        with_metric = [i for i in q.items() if i.primary_metric_name]
        assert with_metric, "expected issues with primary_metric"
        sample = with_metric[0]
        assert sample.primary_metric_name
        assert isinstance(sample.primary_metric_value, float)


# ---------------------------------------------------------------------------
# G2 — load review.tsv (lightweight)
# ---------------------------------------------------------------------------


class TestLoadReviewTsv:
    def test_loads_from_tsv(self, report_and_tsv):
        _, tsv_path, rep = report_and_tsv
        q = QualityReviewQueue()
        n = q.load_review_tsv(tsv_path)
        assert n == len(rep.issues)
        assert q.report_path is None
        assert q.review_tsv_path == tsv_path
        # tsv is lightweight: no rule_id, no primary metric
        for item in q.items():
            assert item.issue_id
            assert item.rule_name
            assert item.primary_metric_name == ""

    def test_tsv_and_report_yield_same_issue_ids(self, report_and_tsv):
        report_path, tsv_path, _ = report_and_tsv
        qr = QualityReviewQueue()
        qr.load_report(report_path)
        qt = QualityReviewQueue()
        qt.load_review_tsv(tsv_path)
        assert {i.issue_id for i in qr} == {i.issue_id for i in qt}


class TestIssueIdentity:
    def test_issue_ids_survive_different_run_ids(self, tmp_path):
        ann = tmp_path / "a.json"
        _make_annotation(str(ann))
        profile = load_threshold_profile()
        rep_a = run_quality_check(
            [str(ann)], profile=profile, input_root=str(tmp_path)
        )
        rep_b = run_quality_check(
            [str(ann)],
            profile=profile,
            input_root=str(tmp_path / "single_file_rescan"),
        )
        assert rep_a.run_id != rep_b.run_id
        assert {i.issue_id() for i in rep_a.issues} == {
            i.issue_id() for i in rep_b.issues
        }


# ---------------------------------------------------------------------------
# G3 — merge feedback
# ---------------------------------------------------------------------------


class TestMergeFeedback:
    def test_merge_applies_decision(self, report_and_tsv, tmp_path):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        # pre-mark one issue, write feedback, then re-merge
        target = q.items()[0]
        q.update_review(target.issue_id, status="false_positive", reviewer="t")
        fb = tmp_path / "fb.tsv"
        q.write_feedback(str(fb))

        q2 = QualityReviewQueue()
        q2.load_report(report_path)
        updated = q2.merge_feedback(str(fb))
        assert updated == 1
        merged = q2.get(target.issue_id)
        assert merged.status == "false_positive"
        assert merged.decision == "false_positive"
        assert merged.final_action == "ignored"
        assert merged.reviewer == "t"

    def test_merge_ignores_unknown_issue_ids(self, tmp_path):
        # feedback referencing an issue_id not in the queue is skipped
        fb = tmp_path / "fb.tsv"
        cols = [
            "issue_id",
            "run_id",
            "file_path",
            "shape_index",
            "rule_name",
            "original_severity",
            "decision",
            "final_action",
            "reviewer",
            "reviewed_at",
            "note",
        ]
        with open(fb, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t")
            w.writeheader()
            w.writerow(
                {
                    "issue_id": "nonexistent",
                    "run_id": "r",
                    "file_path": "/x.json",
                    "shape_index": 0,
                    "rule_name": "r",
                    "original_severity": "warning",
                    "decision": "false_positive",
                    "final_action": "ignored",
                    "reviewer": "",
                    "reviewed_at": "",
                    "note": "",
                }
            )
        q = QualityReviewQueue()
        updated = q.merge_feedback(str(fb))
        assert updated == 0


# ---------------------------------------------------------------------------
# G4 — write feedback round-trips
# ---------------------------------------------------------------------------


class TestWriteFeedback:
    def test_write_then_read_back(self, report_and_tsv, tmp_path):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        # mark two issues differently
        items = q.items()
        q.update_review(items[0].issue_id, status="fixed", reviewer="a")
        q.update_review(items[1].issue_id, status="acceptable", reviewer="b")
        fb = tmp_path / "fb.tsv"
        q.write_feedback(str(fb))

        q2 = QualityReviewQueue()
        q2.load_report(report_path)
        q2.merge_feedback(str(fb))
        assert q2.get(items[0].issue_id).status == "fixed"
        assert q2.get(items[0].issue_id).decision == "fixed"
        assert q2.get(items[1].issue_id).status == "acceptable"
        assert q2.get(items[1].issue_id).decision == "acceptable"
        # the third, unreviewed item stays pending
        if len(items) > 2:
            assert q2.get(items[2].issue_id).status == "pending"
            assert q2.get(items[2].issue_id).decision == ""

    def test_invalid_decision_rejected(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        first = q.items()[0]
        with pytest.raises(ValueError):
            q.update_review(first.issue_id, decision="bogus")


# ---------------------------------------------------------------------------
# G5 — empty decision excluded from stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty_decision_not_counted_as_reviewed(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        s = q.stats()
        assert s["reviewed"] == 0
        assert s["unreviewed"] == s["total"]
        assert s["false_positive"] == 0

    def test_stats_after_reviews(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        items = q.items()
        q.update_review(items[0].issue_id, status="confirmed_error")
        q.update_review(items[1].issue_id, status="false_positive")
        if len(items) > 2:
            q.update_review(items[2].issue_id, status="needs_discussion")
        s = q.stats()
        assert s["reviewed"] == len(items)
        assert s["by_status"]["confirmed_error"] == 1
        assert s["by_status"]["false_positive"] == 1
        assert s["by_status"]["needs_discussion"] == 1


# ---------------------------------------------------------------------------
# G7 — rescan preserves feedback, tags disappeared issues
# ---------------------------------------------------------------------------


class TestRescanFile:
    def test_rescan_preserves_feedback_and_tags_resolved(
        self, report_and_tsv, tmp_path
    ):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        # review all current issues
        for item in q.items():
            q.update_review(
                item.issue_id, status="false_positive", reviewer="t"
            )

        # simulate a re-scan of the same file where one issue disappeared
        target_file = q.items()[0].file_path
        surviving = q.items()[1:]  # drop the first issue
        new_items = [
            QualityReviewItem(
                issue_id=item.issue_id,
                run_id=item.run_id,
                file_path=item.file_path,
                shape_index=item.shape_index,
                rule_id=item.rule_id,
                rule_name=item.rule_name,
                severity=item.severity,
                message=item.message,
            )
            for item in surviving
        ]
        result = q.rescan_file(target_file, new_items)

        # the disappeared issue is now resolved_after_rescan but keeps feedback
        disappeared = q.items()[0]
        assert disappeared.status == "resolved_after_rescan"
        assert disappeared.decision == "false_positive"  # feedback kept
        assert disappeared.reviewer == "t"
        # surviving items keep their reviewed state
        for item in q.items()[1:]:
            assert item.status == "false_positive"
        # summary counts
        assert result["resolved"] == 1
        assert result["total"] == len(q.items())

    def test_rescan_adds_new_issues(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        before = q.total
        target_file = q.items()[0].file_path
        brand_new = QualityReviewItem(
            issue_id="brand-new-id",
            run_id="run",
            file_path=target_file,
            shape_index=5,
            rule_id="L2-99",
            rule_name="synthetic",
            severity="error",
            message="new issue from rescan",
        )
        existing = list(q.items())
        new_items = [
            QualityReviewItem(
                issue_id=i.issue_id,
                run_id=i.run_id,
                file_path=i.file_path,
                shape_index=i.shape_index,
                rule_id=i.rule_id,
                rule_name=i.rule_name,
                severity=i.severity,
                message=i.message,
            )
            for i in existing
        ] + [brand_new]
        result = q.rescan_file(target_file, new_items)
        assert result["added"] == 1
        assert q.total == before + 1
        new = q.get("brand-new-id")
        assert new is not None
        assert new.status == "pending"

    def test_rescan_does_not_touch_other_files(self, report_and_tsv, tmp_path):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        # add a fake item in a different file
        other = QualityReviewItem(
            issue_id="other-file-id",
            run_id="r",
            file_path="/different/file.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="x",
            severity="warning",
            message="m",
        )
        q._items[other.issue_id] = other
        target_file = q.items()[0].file_path
        # rescan with empty new list → all target-file items resolved,
        # other-file item untouched
        q.rescan_file(target_file, [])
        assert q.get("other-file-id").status == "pending"
        # target file items resolved
        for item in q.items():
            if osp.normpath(item.file_path) == osp.normpath(target_file):
                assert item.status == "resolved_after_rescan"


# ---------------------------------------------------------------------------
# status <-> decision mapping (section 8.2)
# ---------------------------------------------------------------------------


class TestStatusDecisionMapping:
    def test_fixed_maps_to_fixed_action(self):
        q = QualityReviewQueue()
        q._items["x"] = QualityReviewItem(
            issue_id="x",
            run_id="r",
            file_path="/f.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
        )
        q.update_review("x", status="fixed")
        item = q.get("x")
        assert item.decision == "fixed"
        assert item.final_action == "fixed_box"

    def test_confirmed_error_maps_correctly(self):
        q = QualityReviewQueue()
        q._items["x"] = QualityReviewItem(
            issue_id="x",
            run_id="r",
            file_path="/f.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
        )
        q.update_review("x", status="confirmed_error")
        item = q.get("x")
        assert item.decision == "confirmed_error"
        assert item.final_action == "none"

    def test_all_statuses_map(self):
        for status, (dec, act) in STATUS_TO_FEEDBACK.items():
            if status in ("pending", "viewed", "resolved_after_rescan"):
                continue
            assert (
                status_from_decision(dec) == status
            ), f"{status} -> {dec} -> {status_from_decision(dec)}"

    def test_invalid_status_rejected(self):
        q = QualityReviewQueue()
        q._items["x"] = QualityReviewItem(
            issue_id="x",
            run_id="r",
            file_path="/f.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
        )
        with pytest.raises(ValueError):
            q.update_review("x", status="bogus")


# ---------------------------------------------------------------------------
# filter / sort
# ---------------------------------------------------------------------------


class TestFilterSort:
    def test_filter_by_severity(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        for sev in q.unique_severities():
            items = q.filter(severity=sev)
            assert all(i.severity == sev for i in items)

    def test_filter_by_current_file(self, report_and_tsv):
        report_path, _, _ = report_and_tsv
        q = QualityReviewQueue()
        q.load_report(report_path)
        target = q.items()[0].file_path
        items = q.filter(file_path=target)
        assert all(
            osp.normpath(i.file_path) == osp.normpath(target) for i in items
        )

    def test_filter_by_current_image_basename(self):
        q = QualityReviewQueue()
        q._items["a"] = QualityReviewItem(
            issue_id="a",
            run_id="r",
            file_path="/labels/file_one.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
        )
        items = q.sorted_items(file_path="/images/file_one.jpg")
        assert [i.issue_id for i in items] == ["a"]

    def test_sorted_error_before_warning(self):
        q = QualityReviewQueue()
        for i, sev in enumerate(["info", "warning", "error"]):
            q._items[f"id{i}"] = QualityReviewItem(
                issue_id=f"id{i}",
                run_id="r",
                file_path="/f.json",
                shape_index=i,
                rule_id="L2-01",
                rule_name="n",
                severity=sev,
                message="m",
            )
        items = q.sorted_items()
        assert items[0].severity == "error"
        assert items[-1].severity == "info"

    def test_sorted_unreviewed_first(self):
        q = QualityReviewQueue()
        q._items["reviewed"] = QualityReviewItem(
            issue_id="reviewed",
            run_id="r",
            file_path="/f.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
            status="false_positive",
            decision="false_positive",
        )
        q._items["pending"] = QualityReviewItem(
            issue_id="pending",
            run_id="r",
            file_path="/f.json",
            shape_index=1,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
        )
        items = q.sorted_items()
        assert items[0].issue_id == "pending"

    def test_sorted_uses_metric_direction(self):
        q = QualityReviewQueue()
        q._items["low"] = QualityReviewItem(
            issue_id="low",
            run_id="r",
            file_path="/f.json",
            shape_index=0,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
            primary_metric_value=0.1,
            primary_metric_direction="lower_is_worse",
        )
        q._items["high"] = QualityReviewItem(
            issue_id="high",
            run_id="r",
            file_path="/f.json",
            shape_index=1,
            rule_id="L2-01",
            rule_name="n",
            severity="warning",
            message="m",
            primary_metric_value=0.9,
            primary_metric_direction="lower_is_worse",
        )
        assert [i.issue_id for i in q.sorted_items()] == ["low", "high"]
