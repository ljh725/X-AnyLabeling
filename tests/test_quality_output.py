"""Output structure tests: review.tsv + report.json + no-mutation guarantee.

Run: pytest tests/test_quality_output.py -v
"""

import json
import os.path as osp
import shutil
import sys
from collections import Counter

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    load_threshold_profile,
    run_quality_check,
    write_report_json,
    write_review_tsv,
)
from anylabeling.views.labeling.widgets.inspector.quality.report_writer import (  # noqa: E402
    REVIEW_TSV_COLUMNS,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _shape(label, st, points, gid=None):
    s = {"label": label, "shape_type": st, "points": points}
    if gid is not None:
        s["group_id"] = gid
    return s


@pytest.fixture
def sample_dir(tmp_path):
    """One annotation file exercising several L1/L2 paths."""
    data = {
        "imagePath": "img.jpg",
        "imageWidth": 1000,
        "imageHeight": 1000,
        "shapes": [
            # person + head + face in same group, face overflows head
            _shape("person", "rectangle", [[100, 100], [400, 600]], gid=1),
            _shape("head", "rectangle", [[150, 120], [210, 180]], gid=1),
            _shape("face", "rectangle", [[140, 110], [260, 190]], gid=1),
            # a keypoint outside the person
            _shape("nose", "point", [[980, 980]], gid=1),
            # a structurally-broken shape (empty label)
            {
                "label": "",
                "shape_type": "rectangle",
                "points": [[0, 0], [1, 1]],
            },
            # a second person group, head without matched person nearby
            _shape("person", "rectangle", [[700, 700], [900, 950]], gid=2),
            _shape("head", "rectangle", [[710, 710], [750, 750]], gid=2),
        ],
    }
    fp = tmp_path / "ann.json"
    fp.write_text(json.dumps(data), encoding="utf-8")
    return str(fp)


@pytest.fixture
def profile():
    return load_threshold_profile()


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class TestRunQualityCheck:
    def test_returns_report_with_counts(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        assert rep.total_files == 1
        assert rep.total_shapes == 7
        assert rep.total_issues > 0
        assert rep.run_id
        assert rep.created_at
        assert rep.threshold_profile == "v0_default"

    def test_every_issue_has_stable_id(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        ids = [i.issue_id() for i in rep.issues]
        assert all(ids)
        assert len(ids) == len(set(ids)), "issue_ids must be unique"

    def test_run_id_and_issue_ids_are_stable_across_reruns(
        self, sample_dir, profile, tmp_path
    ):
        rep1 = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        rep2 = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )

        assert rep1.run_id == rep2.run_id
        assert [i.issue_id() for i in rep1.issues] == [
            i.issue_id() for i in rep2.issues
        ]

    def test_every_issue_has_primary_metric(
        self, sample_dir, profile, tmp_path
    ):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        for issue in rep.issues:
            assert (
                issue.primary_metric is not None
            ), f"{issue.rule_id} missing primary_metric"
            assert issue.primary_metric.name
            assert issue.primary_metric.direction

    def test_thresholds_hit_present_when_severity_assigned(
        self, sample_dir, profile, tmp_path
    ):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        for issue in rep.issues:
            assert (
                issue.thresholds_hit
            ), f"{issue.rule_id} missing thresholds_hit"
            assert issue.thresholds_hit.get("level") == issue.severity

    def test_does_not_modify_input_json(self, sample_dir, profile, tmp_path):
        original = open(sample_dir, "r", encoding="utf-8").read()
        run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        after = open(sample_dir, "r", encoding="utf-8").read()
        assert original == after, "quality check must not mutate input JSON"


# ---------------------------------------------------------------------------
# review.tsv
# ---------------------------------------------------------------------------


class TestReviewTsv:
    def test_columns_match_spec(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        out = tmp_path / "review.tsv"
        write_review_tsv(rep, str(out))
        header = out.read_text(encoding="utf-8").splitlines()[0]
        cols = header.split("\t")
        assert cols == REVIEW_TSV_COLUMNS

    def test_row_count_matches_issues(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        out = tmp_path / "review.tsv"
        write_review_tsv(rep, str(out))
        lines = out.read_text(encoding="utf-8").splitlines()
        # header + one row per issue
        assert len(lines) == rep.total_issues + 1


# ---------------------------------------------------------------------------
# report.json
# ---------------------------------------------------------------------------


class TestReportJson:
    def test_top_level_schema(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        out = tmp_path / "report.json"
        write_report_json(rep, str(out))
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "l1_l2_qc.v1"
        assert payload["run_id"] == rep.run_id
        assert payload["threshold_profile"] == "v0_default"
        assert "created_at" in payload
        assert "source" in payload
        assert "thresholds" in payload
        assert "summary" in payload
        assert isinstance(payload["issues"], list)

    def test_summary_counts(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        out = tmp_path / "report.json"
        write_report_json(rep, str(out))
        payload = json.loads(out.read_text(encoding="utf-8"))
        s = payload["summary"]
        assert s["total_files"] == 1
        assert s["total_shapes"] == 7
        assert s["total_issues"] == rep.total_issues
        assert sum(s["issues_by_severity"].values()) == s["total_issues"]

    def test_issue_has_required_fields(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        out = tmp_path / "report.json"
        write_report_json(rep, str(out))
        payload = json.loads(out.read_text(encoding="utf-8"))
        required = {
            "issue_id",
            "rule_id",
            "rule_name",
            "severity",
            "file_path",
            "shape_index",
            "message",
            "primary_metric",
            "metrics",
            "thresholds_hit",
            "review",
        }
        for issue in payload["issues"]:
            missing = required - set(issue.keys())
            assert (
                not missing
            ), f"issue missing {missing}: {issue.get('rule_id')}"

    def test_match_issue_has_candidates(self, sample_dir, profile, tmp_path):
        rep = run_quality_check(
            [sample_dir], profile=profile, input_root=str(tmp_path)
        )
        out = tmp_path / "report.json"
        write_report_json(rep, str(out))
        payload = json.loads(out.read_text(encoding="utf-8"))
        match_issues = [
            i for i in payload["issues"] if i.get("match") is not None
        ]
        assert match_issues, "expected at least one match-bearing issue"
        for mi in match_issues:
            assert mi["match"] is not None
            assert "matched_shape_index" in mi["match"]
