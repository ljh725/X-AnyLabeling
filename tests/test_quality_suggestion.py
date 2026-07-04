"""threshold_suggestion.json tests: 9-level trigger, pending, feedback.

Run: pytest tests/test_quality_suggestion.py -v
"""

import csv
import json
import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    SuggestionContext,
    generate_threshold_suggestion,
    load_threshold_profile,
    run_quality_check,
    write_report_json,
)
from anylabeling.views.labeling.widgets.inspector.quality.feedback import (  # noqa: E402
    aggregate_by_rule,
    read_review_feedback,
    write_review_feedback_template,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _feedback_row(
    issue_id="x",
    rule_name="face_inside_matched_head",
    decision="confirmed_error",
    final_action="none",
    run_id="r",
):
    return {
        "issue_id": issue_id,
        "run_id": run_id,
        "file_path": "/a.json",
        "shape_index": 0,
        "rule_name": rule_name,
        "original_severity": "warning",
        "decision": decision,
        "final_action": final_action,
        "reviewer": "tester",
        "reviewed_at": "2026-07-03T00:00:00",
        "note": "",
    }


def _write_feedback_tsv(path, rows):
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
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _make_report(tmp_path, rule_name="face_inside_matched_head"):
    """Produce a real report.json via the checker so issue_ids are real."""
    data = {
        "imagePath": "i.jpg",
        "imageWidth": 1000,
        "imageHeight": 1000,
        "shapes": [
            {
                "label": "person",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[0, 0], [100, 200]],
            },
            {
                "label": "head",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[10, 10], [40, 40]],
            },
            {
                "label": "face",
                "shape_type": "rectangle",
                "group_id": 1,
                "points": [[5, 5], [60, 60]],
            },
        ],
    }
    fp = tmp_path / "a.json"
    fp.write_text(json.dumps(data), encoding="utf-8")
    profile = load_threshold_profile()
    rep = run_quality_check(
        [str(fp)], profile=profile, input_root=str(tmp_path)
    )
    report_path = tmp_path / "report.json"
    write_report_json(rep, str(report_path))
    return str(report_path), rep


# ---------------------------------------------------------------------------
# feedback reader + aggregation
# ---------------------------------------------------------------------------


class TestFeedbackReader:
    def test_reads_valid_rows(self, tmp_path):
        p = tmp_path / "fb.tsv"
        _write_feedback_tsv(
            str(p),
            [
                _feedback_row(decision="fixed"),
                _feedback_row(issue_id="y", decision="false_positive"),
            ],
        )
        res = read_review_feedback(str(p))
        assert res.ok
        assert len(res.rows) == 2
        assert res.rows[0].is_true_error
        assert res.rows[1].is_false_positive

    def test_invalid_decision_recorded_as_error(self, tmp_path):
        p = tmp_path / "fb.tsv"
        _write_feedback_tsv(
            str(p),
            [_feedback_row(decision="bogus")],
        )
        res = read_review_feedback(str(p), strict=True)
        assert res.errors
        assert len(res.rows) == 0

    def test_needs_discussion_excluded_from_rate_denominator(self):
        rows = [
            _feedback_row(issue_id=str(i), decision="needs_discussion")
            for i in range(5)
        ]
        rows += [_feedback_row(issue_id="ok", decision="confirmed_error")]
        from anylabeling.views.labeling.widgets.inspector.quality.feedback import (
            FeedbackRow,
        )

        parsed = [
            FeedbackRow(
                issue_id=r["issue_id"],
                run_id=r["run_id"],
                file_path=r["file_path"],
                shape_index=r["shape_index"],
                rule_name=r["rule_name"],
                original_severity=r["original_severity"],
                decision=r["decision"],
                final_action=r["final_action"],
            )
            for r in rows
        ]
        agg = aggregate_by_rule(parsed)
        stats = agg["face_inside_matched_head"]
        # 6 total rows, 5 discussion → denom = 1
        assert stats["all_review_rows"] == 6
        assert stats["needs_discussion_count"] == 5
        assert stats["reviewed_count"] == 1
        assert stats["true_error_count"] == 1
        assert stats["true_error_rate"] == 1.0
        assert stats["discussion_rate"] == round(5 / 6, 3)

    def test_blank_decision_rows_are_ignored_when_non_strict(self, tmp_path):
        p = tmp_path / "fb.tsv"
        _write_feedback_tsv(
            str(p),
            [
                _feedback_row(issue_id="blank", decision=""),
                _feedback_row(issue_id="done", decision="acceptable"),
            ],
        )

        res = read_review_feedback(str(p), strict=False)

        assert res.ok
        assert len(res.rows) == 1
        assert res.rows[0].issue_id == "done"


class TestPrepareFeedbackTemplate:
    def test_template_prefills_review_metadata(self, tmp_path):
        report_path, rep = _make_report(tmp_path)
        out = tmp_path / "review_feedback.tsv"

        result = write_review_feedback_template(
            report_path=report_path,
            output_path=str(out),
            reviewer="alice",
        )

        rows = list(csv.DictReader(open(out, encoding="utf-8"), delimiter="\t"))
        assert result.total_rows == len(rep.issues)
        assert result.blank_rows == len(rep.issues)
        assert rows[0]["issue_id"]
        assert rows[0]["run_id"] == rep.run_id
        assert rows[0]["original_severity"]
        assert rows[0]["final_action"] == "none"
        assert rows[0]["reviewer"] == "alice"
        assert "message" in rows[0]
        assert "primary_metric_value" in rows[0]

    def test_template_preserves_existing_decisions(self, tmp_path):
        report_path, rep = _make_report(tmp_path)
        existing = tmp_path / "old_feedback.tsv"
        out = tmp_path / "review_feedback.tsv"
        reviewed_issue = rep.issues[0]
        _write_feedback_tsv(
            str(existing),
            [
                _feedback_row(
                    issue_id=reviewed_issue.issue_id(),
                    rule_name=reviewed_issue.rule_name,
                    decision="false_positive",
                    final_action="ignored",
                    run_id=rep.run_id,
                )
            ],
        )

        result = write_review_feedback_template(
            report_path=report_path,
            output_path=str(out),
            existing_feedback_path=str(existing),
            reviewer="bob",
        )

        rows = list(csv.DictReader(open(out, encoding="utf-8"), delimiter="\t"))
        by_id = {row["issue_id"]: row for row in rows}
        preserved = by_id[reviewed_issue.issue_id()]
        assert result.preserved_rows == 1
        assert preserved["decision"] == "false_positive"
        assert preserved["final_action"] == "ignored"
        assert preserved["reviewer"] == "tester"


# ---------------------------------------------------------------------------
# 9-level trigger (validated via direct _pick_action)
# ---------------------------------------------------------------------------


class TestPickAction:
    def _pick(self, **kw):
        from anylabeling.views.labeling.widgets.inspector.quality import (
            threshold_suggestion as ts,
        )

        defaults = dict(
            reviewed=100,
            true_err_rate=0.5,
            fp_rate=0.1,
            acc_rate=0.1,
            disc_rate=0.05,
        )
        defaults.update(kw)
        return ts._pick_action(
            defaults["reviewed"],
            defaults["true_err_rate"],
            defaults["fp_rate"],
            defaults["acc_rate"],
            defaults["disc_rate"],
        )

    def test_p1_require_more_review(self):
        assert self._pick(reviewed=10) == "require_more_review"

    def test_p2_definition_review(self):
        assert self._pick(disc_rate=0.30) == "definition_review"

    def test_p3_disable_as_strong_rule(self):
        assert (
            self._pick(fp_rate=0.65, true_err_rate=0.20)
            == "disable_as_strong_rule"
        )

    def test_p4_relax_threshold(self):
        assert self._pick(fp_rate=0.55) == "relax_threshold"

    def test_p5_downgrade_severity(self):
        assert self._pick(acc_rate=0.45, fp_rate=0.20) == "downgrade_severity"

    def test_p6_keep_threshold(self):
        assert self._pick(true_err_rate=0.80, fp_rate=0.10) == "keep_threshold"

    def test_p7_tighten_threshold(self):
        """Very strong reviewed evidence should suggest tightening."""
        assert (
            self._pick(true_err_rate=0.90, fp_rate=0.05, reviewed=150)
            == "tighten_threshold"
        )

    def test_p1_beats_p6(self):
        # reviewed < 30 even with great rates → require_more_review
        assert self._pick(reviewed=5, true_err_rate=0.95, fp_rate=0.01) == (
            "require_more_review"
        )


# ---------------------------------------------------------------------------
# generate_threshold_suggestion end-to-end
# ---------------------------------------------------------------------------


class TestGenerateSuggestion:
    def test_output_schema_and_pending(self, tmp_path):
        report_path, rep = _make_report(tmp_path)
        # craft feedback rows for every issue of one rule
        target_rule = "face_inside_matched_head"
        issue_ids = [
            i.issue_id() for i in rep.issues if i.rule_name == target_rule
        ]
        if not issue_ids:
            # fall back to whatever rule fired
            target_rule = rep.issues[0].rule_name
            issue_ids = [rep.issues[0].issue_id()]
        rows = []
        for iid in issue_ids * 35:  # pad to 35 reviews → reviewed >= 30
            rows.append(
                _feedback_row(
                    issue_id=iid,
                    rule_name=target_rule,
                    decision="confirmed_error",
                )
            )
        fb_path = tmp_path / "fb.tsv"
        _write_feedback_tsv(str(fb_path), rows)
        out_path = tmp_path / "sug.json"

        ctx = SuggestionContext(
            report_path=report_path,
            feedback_path=str(fb_path),
            base_threshold_profile="v0_default",
        )
        generate_threshold_suggestion(ctx, str(out_path))
        payload = json.loads(out_path.read_text(encoding="utf-8"))

        assert payload["schema_version"] == "threshold_suggestion.v1"
        assert payload["source"]["base_threshold_profile"] == "v0_default"
        assert "rule_suggestions" in payload
        # approval ALWAYS pending
        for s in payload["rule_suggestions"]:
            assert s["approval"]["status"] == "pending"
            assert s["requires_human_approval"] is True
            assert s["suggested_action"] in {
                "keep_threshold",
                "relax_threshold",
                "tighten_threshold",
                "downgrade_severity",
                "upgrade_severity",
                "rewrite_message",
                "split_rule",
                "disable_as_strong_rule",
                "require_more_review",
                "definition_review",
            }

    def test_global_summary_counts(self, tmp_path):
        report_path, rep = _make_report(tmp_path)
        out_path = tmp_path / "sug.json"
        fb_path = tmp_path / "fb.tsv"
        _write_feedback_tsv(str(fb_path), [])  # no feedback → all unreviewed
        ctx = SuggestionContext(
            report_path=report_path,
            feedback_path=str(fb_path),
            base_threshold_profile="v0_default",
        )
        generate_threshold_suggestion(ctx, str(out_path))
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        gs = payload["global_summary"]
        assert gs["total_rules"] == len(payload["rule_suggestions"])
        # no reviews → all rules require_more_review
        assert gs["rules_need_more_review"] == gs["total_rules"]
        assert gs["rules_ready_for_adjustment"] == 0

    def test_suggestion_includes_review_stats_and_metric_analysis(
        self, tmp_path
    ):
        report_path, rep = _make_report(tmp_path)
        out_path = tmp_path / "sug.json"
        fb_path = tmp_path / "fb.tsv"
        _write_feedback_tsv(str(fb_path), [])
        ctx = SuggestionContext(
            report_path=report_path,
            feedback_path=str(fb_path),
            base_threshold_profile="v0_default",
        )
        generate_threshold_suggestion(ctx, str(out_path))
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        for s in payload["rule_suggestions"]:
            assert "review_stats" in s
            assert "metric_analysis" in s
            assert "reason" in s
            assert "current" in s
            assert "proposed" in s
