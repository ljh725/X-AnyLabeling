"""Threshold evaluation tests: direction, two-sided, error_requires.

Run: pytest tests/test_quality_thresholds.py -v
"""

import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from anylabeling.views.labeling.widgets.inspector.quality.severity_eval import (  # noqa: E402
    evaluate_severity,
)
from anylabeling.views.labeling.widgets.inspector.quality.threshold_profile import (  # noqa: E402
    RuleThreshold,
)


def _rule(
    direction,
    warning=None,
    error=None,
    error_requires=None,
):
    return RuleThreshold(
        rule_id="T",
        rule_name="t",
        enabled=True,
        default_severity="warning",
        primary_metric="m",
        direction=direction,
        warning_threshold=warning,
        error_threshold=error,
        error_requires=error_requires or [],
    )


# ---------------------------------------------------------------------------
# higher_is_worse
# ---------------------------------------------------------------------------


class TestHigherIsWorse:
    def test_below_warning_no_hit(self):
        rule = _rule("higher_is_worse", warning=0.10, error=0.20)
        sev, hit = evaluate_severity(rule, 0.05)
        assert sev is None

    def test_warning_zone(self):
        rule = _rule("higher_is_worse", warning=0.10, error=0.20)
        sev, hit = evaluate_severity(rule, 0.15)
        assert sev == "warning"
        assert hit["level"] == "warning"

    def test_error_zone_no_requires(self):
        rule = _rule("higher_is_worse", warning=0.10, error=0.20)
        sev, _ = evaluate_severity(rule, 0.25)
        assert sev == "error"

    def test_error_requires_unsatisfied_downgrades_to_warning(self):
        rule = _rule(
            "higher_is_worse",
            warning=0.10,
            error=0.20,
            error_requires=["needs_confirmation"],
        )
        sev, hit = evaluate_severity(
            rule, 0.25, error_requires_satisfied=False
        )
        assert sev == "warning"
        assert hit["error_requires_satisfied"] is False

    def test_error_requires_satisfied_allows_error(self):
        rule = _rule(
            "higher_is_worse",
            warning=0.10,
            error=0.20,
            error_requires=["needs_confirmation"],
        )
        sev, _ = evaluate_severity(rule, 0.25, error_requires_satisfied=True)
        assert sev == "error"


# ---------------------------------------------------------------------------
# lower_is_worse
# ---------------------------------------------------------------------------


class TestLowerIsWorse:
    def test_warning_when_below(self):
        rule = _rule("lower_is_worse", warning=1.0, error=0.5)
        sev, _ = evaluate_severity(rule, 0.7)
        assert sev == "warning"

    def test_error_when_far_below(self):
        rule = _rule("lower_is_worse", warning=1.0, error=0.5)
        sev, _ = evaluate_severity(rule, 0.3)
        assert sev == "error"


# ---------------------------------------------------------------------------
# two_sided
# ---------------------------------------------------------------------------


class TestTwoSided:
    def test_inside_band_no_hit(self):
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
        )
        sev, _ = evaluate_severity(rule, 0.30)
        assert sev is None

    def test_below_min_warning(self):
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
        )
        sev, _ = evaluate_severity(rule, 0.02)
        assert sev == "warning"

    def test_above_max_warning(self):
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
        )
        sev, _ = evaluate_severity(rule, 0.75)
        assert sev == "warning"

    def test_above_error_max_is_error(self):
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
        )
        sev, _ = evaluate_severity(rule, 0.90)
        assert sev == "error"

    def test_lower_side_stays_warning_even_at_zero(self):
        # spec: 过小默认 warning
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
            error_requires=["x"],
        )
        sev, _ = evaluate_severity(rule, 0.001)
        assert sev == "warning"


# ---------------------------------------------------------------------------
# higher_abs_is_worse
# ---------------------------------------------------------------------------


class TestHigherAbsIsWorse:
    def test_abs_warning_negative(self):
        rule = _rule(
            "higher_abs_is_worse",
            warning={"abs_z": 3.5},
        )
        sev, _ = evaluate_severity(rule, -4.0)
        assert sev == "warning"

    def test_abs_no_hit(self):
        rule = _rule(
            "higher_abs_is_worse",
            warning={"abs_z": 3.5},
        )
        sev, _ = evaluate_severity(rule, 2.0)
        assert sev is None


# ---------------------------------------------------------------------------
# error_requires integration (L2-03 face>=head)
# ---------------------------------------------------------------------------


class TestErrorRequiresIntegration:
    def test_two_sided_error_requires_unsatisfied_downgrades(self):
        # face/head area: ar=0.90 (above 0.85 max) but face NOT >= head
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
            error_requires=["face_area_ge_head_area"],
        )
        sev, hit = evaluate_severity(
            rule, 0.90, error_requires_satisfied=False
        )
        # above warning max AND above error max → would be error, but
        # requires unsatisfied → warning
        assert sev == "warning"
        assert hit["error_requires_satisfied"] is False

    def test_two_sided_error_requires_satisfied(self):
        rule = _rule(
            "two_sided",
            warning={"min": 0.05, "max": 0.70},
            error={"max": 0.85},
            error_requires=["face_area_ge_head_area"],
        )
        sev, _ = evaluate_severity(rule, 0.90, error_requires_satisfied=True)
        assert sev == "error"


# ---------------------------------------------------------------------------
# profile loader validation
# ---------------------------------------------------------------------------


class TestProfileLoader:
    def test_loads_bundled_v0(self):
        from anylabeling.views.labeling.widgets.inspector.quality import (
            load_threshold_profile,
        )

        p = load_threshold_profile()
        assert p.profile_id == "v0_default"
        assert p.schema_version == "l1_l2_qc.v1"
        # 5 L1 + 13 L2 (including duplicate rectangles)
        assert len(p.rules) == 18
        rule_ids = {r.rule_id for r in p.rules}
        assert {"L2-01", "L2-12", "L1-01", "L1-05"} <= rule_ids

    def test_two_sided_rules_have_min_max(self):
        from anylabeling.views.labeling.widgets.inspector.quality import (
            load_threshold_profile,
        )

        p = load_threshold_profile()
        for r in p.rules:
            if r.direction == "two_sided":
                assert isinstance(r.warning_threshold, dict)
                assert "min" in r.warning_threshold
                assert "max" in r.warning_threshold

    def test_invalid_direction_rejected(self, tmp_path):
        from anylabeling.views.labeling.widgets.inspector.quality import (
            ThresholdProfileError,
            load_threshold_profile,
        )
        import yaml as _yaml

        bad = {
            "profile_id": "x",
            "schema_version": "l1_l2_qc.v1",
            "rules": [
                {
                    "rule_id": "R1",
                    "rule_name": "r1",
                    "enabled": True,
                    "default_severity": "error",
                    "primary_metric": "m",
                    "direction": "sideways_is_worse",
                }
            ],
        }
        fp = tmp_path / "bad.yaml"
        fp.write_text(_yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(ThresholdProfileError):
            load_threshold_profile(str(fp))

    def test_missing_required_field_rejected(self, tmp_path):
        from anylabeling.views.labeling.widgets.inspector.quality import (
            ThresholdProfileError,
            load_threshold_profile,
        )
        import yaml as _yaml

        bad = {
            "profile_id": "x",
            "schema_version": "l1_l2_qc.v1",
            "rules": [
                {
                    "rule_id": "R1",
                    # rule_name missing
                    "enabled": True,
                    "default_severity": "error",
                    "primary_metric": "m",
                    "direction": "higher_is_worse",
                }
            ],
        }
        fp = tmp_path / "bad2.yaml"
        fp.write_text(_yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(ThresholdProfileError):
            load_threshold_profile(str(fp))


# ---------------------------------------------------------------------------
# L2 threshold adapter regressions
# ---------------------------------------------------------------------------


class TestL2ThresholdAdapters:
    def test_match_gap_uses_inverse_min_accept_score(self):
        from anylabeling.views.labeling.widgets.inspector.quality.l2_rules import (  # noqa: E501
            _match_gap_rule,
        )
        from anylabeling.views.labeling.widgets.inspector.quality.matching import (
            MatchingCfg,
        )

        rule = _rule(
            "higher_is_worse",
            warning={"min_accept_score": 0.55},
        )
        adapted = _match_gap_rule(rule, MatchingCfg())

        sev, _ = evaluate_severity(adapted, 0.50)
        assert sev == "warning"

    def test_l2_08_selects_head_person_error_threshold(self):
        from anylabeling.views.labeling.widgets.inspector.quality.l2_rules import (  # noqa: E501
            _rule_with_error_threshold,
        )

        rule = _rule(
            "higher_is_worse",
            warning=0.0,
            error={"face_head": 0.95, "head_person": 0.50},
            error_requires=["head_ge_person_0_50"],
        )
        adapted = _rule_with_error_threshold(rule, "head_person")

        sev, _ = evaluate_severity(
            adapted, 0.55, error_requires_satisfied=True
        )
        assert sev == "error"

    def test_body_part_bands_read_y_rel_keys(self):
        from anylabeling.views.labeling.widgets.inspector.quality.l2_rules import (  # noqa: E501
            _resolve_bands,
        )

        bands = _resolve_bands(
            {
                "shoulder": {
                    "label_aliases": ["l_sho", "r_sho"],
                    "y_rel_min": 0.10,
                    "y_rel_max": 0.50,
                }
            }
        )

        assert bands[0]["y_min"] == 0.10
        assert bands[0]["y_max"] == 0.50
