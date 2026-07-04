"""Matching tests: face→head (strict) and head→person (loose) protocols.

Run: pytest tests/test_quality_matching.py -v
"""

import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from anylabeling.views.labeling.widgets.inspector.quality import (  # noqa: E402
    MatchingCfg,
    matching_cfg_from_profile,
    match_face_to_heads,
    match_head_to_persons,
)
from anylabeling.views.labeling.widgets.inspector.quality.quality_issue import (  # noqa: E402
    QcShape,
)


def _rect(idx, label, x1, y1, x2, y2, gid=None):
    return QcShape(
        shape_index=idx,
        label=label,
        shape_type="rectangle",
        points=[(x1, y1), (x2, y2)],
        group_id=gid,
    )


def _cfg():
    return matching_cfg_from_profile({})


# ---------------------------------------------------------------------------
# face → head
# ---------------------------------------------------------------------------


class TestFaceToHeadHardFilter:
    def test_no_head_no_candidates(self):
        face = _rect(0, "face", 10, 10, 20, 20)
        m = match_face_to_heads(face, [], _cfg())
        assert m.best is None
        assert m.candidates == []
        assert m.match_gap == 1.0

    def test_well_contained_face_matches(self):
        # head fully contains a sensibly-sized face
        head = _rect(1, "head", 0, 0, 100, 100)
        face = _rect(0, "face", 30, 30, 50, 50)  # area ratio 400/10000=0.04
        m = match_face_to_heads(face, [head], _cfg())
        assert m.best is not None
        assert m.best.shape_index == 1
        assert m.match_gap < 1.0

    def test_face_too_big_filtered_by_area_ratio(self):
        # face area ratio > 0.85 → filtered out
        head = _rect(1, "head", 0, 0, 100, 100)
        face = _rect(0, "face", 0, 0, 95, 95)  # ratio ~0.90
        m = match_face_to_heads(face, [head], _cfg())
        assert m.best is None

    def test_face_no_x_overlap_filtered(self):
        head = _rect(1, "head", 0, 0, 50, 50)
        face = _rect(0, "face", 100, 10, 120, 30)  # no x overlap
        m = match_face_to_heads(face, [head], _cfg())
        assert m.best is None

    def test_face_far_from_head_filtered_by_center(self):
        # x and y overlap pass but face center not in expanded head
        head = _rect(1, "head", 0, 0, 40, 40)
        # face barely overlaps but center is far outside expanded head
        face = _rect(0, "face", 38, 38, 80, 80)
        m = match_face_to_heads(face, [head], _cfg())
        assert m.best is None


class TestFaceToHeadScoring:
    def test_picks_highest_scored_head(self):
        # two heads, the closer/better-contained one should win
        good_head = _rect(1, "head", 20, 20, 80, 80)
        far_head = _rect(2, "head", 200, 200, 260, 260)
        face = _rect(0, "face", 35, 35, 55, 55)
        m = match_face_to_heads(face, [good_head, far_head], _cfg())
        assert m.best is not None
        assert m.best.shape_index == 1  # good_head

    def test_candidates_sorted_descending(self):
        heads = [
            _rect(1, "head", 20, 20, 80, 80),  # good
            _rect(2, "head", 25, 25, 90, 90),  # ok
        ]
        face = _rect(0, "face", 35, 35, 55, 55)
        m = match_face_to_heads(face, heads, _cfg())
        scores = [c.score for c in m.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_candidates_limited(self):
        cfg = _cfg()
        cfg.top_n_candidates = 2
        heads = [_rect(i, "head", 10 + i, 10, 60 + i, 60) for i in range(5)]
        face = _rect(0, "face", 30, 30, 45, 45)
        m = match_face_to_heads(face, heads, cfg)
        assert len(m.candidates) <= 2

    def test_ambiguous_when_top2_close(self):
        # two nearly identical heads → ambiguous
        h1 = _rect(1, "head", 20, 20, 80, 80)
        h2 = _rect(2, "head", 22, 22, 82, 82)
        face = _rect(0, "face", 38, 38, 58, 58)
        m = match_face_to_heads(face, [h1, h2], _cfg())
        assert m.ambiguous is True


# ---------------------------------------------------------------------------
# head → person
# ---------------------------------------------------------------------------


class TestHeadToPersonHardFilter:
    def test_no_person_marks_file_has_person_false(self):
        head = _rect(0, "head", 10, 10, 20, 20)
        m = match_head_to_persons(head, [], _cfg())
        assert m.best is None
        assert m.file_has_person is False

    def test_head_above_person_matches(self):
        person = _rect(1, "person", 0, 0, 100, 200)
        head = _rect(0, "head", 40, 10, 60, 40)  # near top
        m = match_head_to_persons(head, [person], _cfg())
        assert m.best is not None
        assert m.best.shape_index == 1

    def test_head_in_lower_body_filtered_by_y_rel(self):
        # head center y at 0.7 * person_h → filtered (> 0.60)
        person = _rect(1, "person", 0, 0, 100, 200)
        head = _rect(0, "head", 40, 140, 60, 160)
        m = match_head_to_persons(head, [person], _cfg())
        assert m.best is None

    def test_head_too_big_filtered_by_area_ratio(self):
        # head/person area > 0.40 → filtered
        person = _rect(1, "person", 0, 0, 100, 100)  # 10000
        head = _rect(0, "head", 0, 0, 80, 80)  # 6400 → 0.64
        m = match_head_to_persons(head, [person], _cfg())
        assert m.best is None


class TestHeadToPersonScoring:
    def test_picks_best_person(self):
        good = _rect(1, "person", 0, 0, 100, 200)
        far = _rect(2, "person", 500, 500, 600, 700)
        head = _rect(0, "head", 40, 10, 60, 40)
        m = match_head_to_persons(head, [good, far], _cfg())
        assert m.best.shape_index == 1

    def test_match_gap_is_one_minus_best_score(self):
        person = _rect(1, "person", 0, 0, 100, 200)
        head = _rect(0, "head", 40, 10, 60, 40)
        m = match_head_to_persons(head, [person], _cfg())
        assert m.match_gap == pytest.approx(1.0 - m.best.score, abs=1e-6)


class TestMatchingCfgFromProfile:
    def test_defaults_when_empty(self):
        cfg = matching_cfg_from_profile({})
        assert cfg.min_accept_score == 0.55
        assert cfg.face_head_filter.min_x_overlap == 0.25
        assert cfg.head_person_filter.min_x_overlap == 0.15

    def test_overrides_from_config(self):
        cfg = matching_cfg_from_profile(
            {
                "matching": {"min_accept_score": 0.7, "top_n_candidates": 5},
                "face_head_hard_filter": {"min_x_overlap": 0.30},
            }
        )
        assert cfg.min_accept_score == 0.7
        assert cfg.top_n_candidates == 5
        assert cfg.face_head_filter.min_x_overlap == 0.30
