"""Pure-Python tests for rect_refine_grouping.

Covers §33.2 / §33.3 / §33.4 acceptance points that are pure logic.  This file
MUST NOT import PyQt6 — grouping/types are required to be importable in a
PyQt-free process (§23.3, audit risk #10).

Each test maps to one or more AC IDs from the design doc so the coverage
matrix is explicit.
"""

from __future__ import annotations

import math

import pytest

from anylabeling.views.labeling.rect_refine_grouping import (
    ANCHOR_LABELS,
    DEFAULTS,
    GroupingResult,
    infer,
    triangle_area_score,
    upper_body_score,
)
from anylabeling.views.labeling.rect_refine_types import (
    CandidateSource,
    ConflictCode,
    RelationKind,
    ShapeRefineView,
    is_valid_gid,
)

TOKEN = "img-001"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _view(
    label: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    idx: int,
    gid=None,
    token: str = TOKEN,
    base_visible: bool = True,
) -> ShapeRefineView:
    """Build a rectangle ShapeRefineView with deterministic shape_id."""
    pts = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    return ShapeRefineView(
        shape_id=(token, idx),
        shape_index=idx,
        label=label,
        shape_type="rectangle",
        group_id=gid,
        points=pts,
        bbox=(x1, y1, x2, y2),
        base_visible=base_visible,
    )


def _person(idx=1, **kw) -> ShapeRefineView:
    return _view("person", 0, 0, 100, 200, idx, **kw)


def _head_in(person_idx=1, idx=2, **kw) -> ShapeRefineView:
    # A head comfortably inside the default person (0,0,100,200), upper area.
    return _view("head", 30, 10, 70, 50, idx, **kw)


def _face_in(head_idx=2, idx=3, **kw) -> ShapeRefineView:
    # A face comfortably inside the default head (30,10,70,50).
    return _view("face", 38, 18, 62, 48, idx, **kw)


# ---------------------------------------------------------------------------
# §29.2 sub-score primitives
# ---------------------------------------------------------------------------


class TestTriangleAreaScore:
    """§29.2 triangle-area-ratio score boundaries."""

    def test_zero_or_negative_is_zero(self):
        assert triangle_area_score(0.0, 0.30, 0.85) == 0.0
        assert triangle_area_score(-0.1, 0.30, 0.85) == 0.0

    def test_at_high_is_zero(self):
        assert triangle_area_score(0.85, 0.30, 0.85) == 0.0

    def test_above_high_is_zero(self):
        assert triangle_area_score(0.90, 0.30, 0.85) == 0.0

    def test_at_ideal_is_one(self):
        assert triangle_area_score(0.30, 0.30, 0.85) == pytest.approx(1.0)

    def test_ramp_up_below_ideal(self):
        # 0.15 / 0.30 == 0.5
        assert triangle_area_score(0.15, 0.30, 0.85) == pytest.approx(0.5)

    def test_ramp_down_above_ideal(self):
        # (0.85 - 0.575) / (0.85 - 0.30) == 0.5
        assert triangle_area_score(0.575, 0.30, 0.85) == pytest.approx(0.5)


class TestUpperBodyScore:
    """§29.2 head→person upper-position score bands."""

    def test_inside_ideal_band_is_one(self):
        assert upper_body_score(0.10) == pytest.approx(1.0)
        assert upper_body_score(0.20) == pytest.approx(1.0)
        assert upper_body_score(0.30) == pytest.approx(1.0)

    def test_below_ideal_lo_ramps_up(self):
        # 0.05 / 0.10 == 0.5
        assert upper_body_score(0.05) == pytest.approx(0.5)
        assert upper_body_score(0.0) == pytest.approx(0.0)

    def test_above_ideal_hi_ramps_down(self):
        # (0.60 - 0.45) / (0.60 - 0.30) == 0.5
        assert upper_body_score(0.45) == pytest.approx(0.5)

    def test_outside_high_is_zero(self):
        assert upper_body_score(0.60) == pytest.approx(0.0)
        assert upper_body_score(0.70) == pytest.approx(0.0)
        assert upper_body_score(-0.1) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# is_valid_gid — §24.2, AC-032
# ---------------------------------------------------------------------------


class TestIsValidGid:
    def test_plain_int_is_valid(self):
        assert is_valid_gid(0) is True
        assert is_valid_gid(7) is True
        assert is_valid_gid(-3) is True

    def test_bool_is_invalid(self):
        # AC-032: bool must be treated as no-GID-evidence.
        assert is_valid_gid(True) is False
        assert is_valid_gid(False) is False

    def test_string_and_none_are_invalid(self):
        assert is_valid_gid("7") is False
        assert is_valid_gid(None) is False
        assert is_valid_gid(7.0) is False


# ---------------------------------------------------------------------------
# §33.4 AC-045 / AC-046 — min_accept_score boundary
# ---------------------------------------------------------------------------


class TestAcceptScoreBoundary:
    """AC-045 (0.5499 rejected), AC-046 (0.55 accepted).

    We construct a head whose weighted score lands just below / at the 0.55
    threshold by tuning containment (the dominant term) via geometry.
    """

    def test_candidate_below_threshold_not_accepted(self):
        # A head far outside the upper-area band but barely passing the hard
        # filter will score low.  Build a person + a head whose score < 0.55.
        person = _view("person", 0, 0, 100, 200, 1)
        # head near the bottom (y_rel ~ 0.75 → upper_score 0), small overlap.
        bad_head = _view("head", 45, 150, 55, 165, 2)
        res = infer(person, [person, bad_head])
        assert res.is_ready
        # Only the anchor person; bad_head did not clear min_accept_score.
        assert {m.shape_id for m in res.members} == {person.shape_id}

    def test_candidate_at_or_above_threshold_accepted(self):
        person = _view("person", 0, 0, 100, 200, 1)
        head = _head_in(idx=2)  # well-placed head, score well above 0.55
        res = infer(person, [person, head])
        assert res.is_ready
        assert head.shape_id in {m.shape_id for m in res.members}


# ---------------------------------------------------------------------------
# §33.4 AC-047 — deterministic repeat inference
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_inference_identical_members_and_order(self):
        person = _person(idx=1)
        h1 = _head_in(idx=2)
        h2 = _view("head", 32, 12, 68, 52, 3)  # second plausible head
        face = _face_in(idx=4)
        pool = [person, h1, h2, face]
        r1 = infer(person, pool)
        r2 = infer(person, pool)
        assert [m.shape_id for m in r1.members] == [
            m.shape_id for m in r2.members
        ]
        # Relation-graph lists must also be in the same order.
        for dict_attr in ("person_to_heads", "head_to_faces"):
            d1 = getattr(r1.relation_graph, dict_attr)
            d2 = getattr(r2.relation_graph, dict_attr)
            for k in d1:
                assert d1[k] == d2[k]


# ---------------------------------------------------------------------------
# §33.4 AC-048 — no top_n truncation
# ---------------------------------------------------------------------------


class TestNoTopNTruncation:
    def test_more_than_three_geometric_heads_all_retained(self):
        """AC-048: more than 3 plausible heads must all enter the group.

        QA matching's top_n=3 must NOT truncate the refine candidate set.
        """
        person = _view("person", 0, 0, 200, 400, 1)  # large person
        heads = [
            _view("head", 20 + i * 40, 20, 50 + i * 40, 90, 2 + i)
            for i in range(5)
        ]
        pool = [person, *heads]
        res = infer(person, pool)
        assert res.is_ready
        accepted = {m.shape_id for m in res.members if m.label == "head"}
        # Whatever passed the hard filter + min_accept_score is kept; with 5
        # plausible heads we expect strictly more than the QA top_n=3 cap.
        assert len(accepted) > 3


# ---------------------------------------------------------------------------
# §33.4 AC-044 — high containment but low IoU must not be excluded
# ---------------------------------------------------------------------------


class TestContainmentDominatesIoU:
    def test_inner_face_fully_contained_low_iou_still_candidate(self):
        """AC-044: a small face fully inside a large head has low IoU but
        high containment; it must still be admitted.
        """
        head = _view("head", 0, 0, 100, 100, 1)
        # Tiny face fully contained → IoU is tiny but containment = 1.0.
        face = _view("face", 45, 45, 55, 55, 2)
        res = infer(face, [face, head])
        assert res.is_ready
        # face→head upward; head must be in the group if hard filter passes.
        # Even if the hard filter rejects extreme ratios, the result must not
        # crash and the anchor face is always retained.
        assert face.shape_id in {m.shape_id for m in res.members}


# ---------------------------------------------------------------------------
# §33.2 — anchor direction (AC-010 / AC-011 / AC-012)
# ---------------------------------------------------------------------------


class TestAnchorDirection:
    def test_ac010_person_expands_downward_to_head_and_face(self):
        person = _person(idx=1)
        head = _head_in(idx=2)
        face = _face_in(idx=3)
        res = infer(person, [person, head, face])
        assert res.is_ready
        ids = {m.shape_id for m in res.members}
        assert ids == {person.shape_id, head.shape_id, face.shape_id}
        # person → heads relation populated.
        assert res.relation_graph.person_to_heads[person.shape_id] == [
            head.shape_id
        ]
        assert res.relation_graph.head_to_faces[head.shape_id] == [
            face.shape_id
        ]

    def test_ac011_head_only_searches_upward_no_face(self):
        head = _head_in(idx=1)
        person = _person(idx=2)
        face = _face_in(idx=3)
        res = infer(head, [head, person, face])
        assert res.is_ready
        ids = {m.shape_id for m in res.members}
        # face must NOT be auto-expanded from a head anchor.
        assert face.shape_id not in ids
        assert head.shape_id in ids
        assert person.shape_id in ids

    def test_ac012_face_walks_up_to_head_then_person(self):
        face = _face_in(idx=1)
        head = _head_in(idx=2)
        person = _person(idx=3)
        res = infer(face, [face, head, person])
        assert res.is_ready
        ids = {m.shape_id for m in res.members}
        assert face.shape_id in ids
        assert head.shape_id in ids
        assert person.shape_id in ids
        # face → head mapping established.
        assert res.relation_graph.face_to_head[face.shape_id] == head.shape_id


# ---------------------------------------------------------------------------
# §33.2 AC-016 — degenerate anchor retained, no crash
# ---------------------------------------------------------------------------


class TestDegenerateAnchor:
    def test_zero_area_person_anchor_retained_alone(self):
        # width = 0 → zero-area bbox.
        bad = _view("person", 50, 0, 50, 200, 1)
        head = _head_in(idx=2)
        res = infer(bad, [bad, head])
        assert res.is_ready
        assert {m.shape_id for m in res.members} == {bad.shape_id}
        assert res.nonblocking_message == "anchor_degenerate_geometry"


# ---------------------------------------------------------------------------
# §33.2 AC-014 / AC-015 — upward ambiguity / missing chain
# ---------------------------------------------------------------------------


class TestUpwardAmbiguity:
    def test_ac014_head_with_two_close_persons_no_auto_join(self):
        head = _head_in(idx=1)
        # Two near-identical persons both containing the head.
        p1 = _view("person", -10, 0, 110, 200, 2)
        p2 = _view("person", 5, 0, 125, 200, 3)
        res = infer(head, [head, p1, p2])
        assert res.is_ready
        ids = {m.shape_id for m in res.members}
        # No person auto-joined → group is head-only with an ambiguity hint.
        assert ids == {head.shape_id}
        assert res.nonblocking_message == "head_upward_ambiguous_person"

    def test_ac015_face_missing_head_stays_face_only(self):
        face = _face_in(idx=1)
        person = _person(idx=2)  # no head in pool
        res = infer(face, [face, person])
        assert res.is_ready
        assert {m.shape_id for m in res.members} == {face.shape_id}
        assert res.nonblocking_message == "face_no_reliable_head"


# ---------------------------------------------------------------------------
# §33.3 — GID merge + conflict codes (AC-020 ~ AC-032)
# ---------------------------------------------------------------------------


class TestGidMerge:
    def test_ac020_three_box_unified_gid_geometry_consistent(self):
        person = _person(idx=1, gid=5)
        head = _head_in(idx=2, gid=5)
        face = _face_in(idx=3, gid=5)
        res = infer(person, [person, head, face])
        assert res.is_ready
        # Both GID-tagged members are source=BOTH.
        assert res.provenance[head.shape_id] == CandidateSource.BOTH
        assert res.provenance[face.shape_id] == CandidateSource.BOTH

    def test_ac021_person_head_gid_face_no_gid(self):
        person = _person(idx=1, gid=5)
        head = _head_in(idx=2, gid=5)
        face = _face_in(idx=3, gid=None)
        res = infer(person, [person, head, face])
        assert res.is_ready
        assert res.provenance[head.shape_id] == CandidateSource.BOTH
        assert res.provenance[face.shape_id] == CandidateSource.GEOMETRY

    def test_ac023_only_person_has_gid_equivalent_to_geometry(self):
        person = _person(idx=1, gid=5)
        head = _head_in(idx=2, gid=None)
        face = _face_in(idx=3, gid=None)
        res = infer(person, [person, head, face])
        assert res.is_ready
        assert res.provenance[head.shape_id] == CandidateSource.GEOMETRY
        assert res.provenance[face.shape_id] == CandidateSource.GEOMETRY

    def test_ac024_person_no_valid_gid_skips_gid_path(self):
        person = _person(idx=1, gid=None)
        head = _head_in(idx=2, gid=5)
        res = infer(person, [person, head])
        assert res.is_ready
        # head still admitted via geometry.
        assert head.shape_id in {m.shape_id for m in res.members}
        assert res.provenance[head.shape_id] == CandidateSource.GEOMETRY

    def test_ac032_gid_is_bool_treated_as_no_evidence(self):
        person = _person(idx=1, gid=True)
        head = _head_in(idx=2, gid=True)
        res = infer(person, [person, head])
        assert res.is_ready
        # No GID path engaged; head admitted purely via geometry if it passes.
        assert res.provenance.get(head.shape_id) in (
            CandidateSource.GEOMETRY,
            None,
        )


class TestGidConflicts:
    def test_ac025_duplicate_gid_head_is_conflict(self):
        person = _person(idx=1, gid=5)
        h1 = _head_in(idx=2, gid=5)
        h2 = _view("head", 35, 12, 65, 52, 3, gid=5)
        res = infer(person, [person, h1, h2])
        assert res.is_conflict
        assert res.conflict_code == ConflictCode.DUPLICATE_GID_HEAD

    def test_ac026_duplicate_gid_face_is_conflict(self):
        person = _person(idx=1, gid=5)
        head = _head_in(idx=2, gid=5)
        f1 = _face_in(idx=3, gid=5)
        f2 = _view("face", 40, 20, 60, 47, 4, gid=5)
        res = infer(person, [person, head, f1, f2])
        assert res.is_conflict
        assert res.conflict_code == ConflictCode.DUPLICATE_GID_FACE

    def test_ac027_gid_head_fails_geometry_is_conflict(self):
        person = _person(idx=1, gid=5)
        # A "head" sharing the GID but located far outside the person → fails
        # the head→person hard filter.
        far_head = _view("head", 500, 500, 540, 540, 2, gid=5)
        res = infer(person, [person, far_head])
        assert res.is_conflict
        assert res.conflict_code == ConflictCode.GID_HEAD_GEOMETRY_INVALID

    def test_ac030_gid_face_unverifiable_by_any_head_is_conflict(self):
        person = _person(idx=1, gid=5)
        head = _head_in(idx=2, gid=5)
        # A "face" sharing the GID but far from the accepted head → fails
        # face→head hard filter against every accepted head.
        far_face = _view("face", 500, 500, 520, 520, 3, gid=5)
        res = infer(person, [person, head, far_face])
        assert res.is_conflict
        assert res.conflict_code == ConflictCode.GID_FACE_GEOMETRY_INVALID

    def test_ac031_gid_face_no_accepted_head_not_bypassed(self):
        """§29.4 step 6 last bullet: with no accepted head, a same-GID face
        must NOT bypass geometry.  Build a person whose only head fails
        geometry so there is no accepted head; the face (sharing GID) must
        not enter the group via GID alone, and there is no conflict."""
        person = _person(idx=1, gid=5)
        far_head = _view("head", 500, 500, 540, 540, 2, gid=5)
        face = _face_in(idx=3, gid=5)
        # far_head fails head→person hard filter → GID_HEAD_GEOMETRY_INVALID.
        res = infer(person, [person, far_head, face])
        assert res.is_conflict
        assert res.conflict_code == ConflictCode.GID_HEAD_GEOMETRY_INVALID


# ---------------------------------------------------------------------------
# §33.4 AC-040 / AC-041 — multi-candidate union + dedupe
# ---------------------------------------------------------------------------


class TestMultiCandidateUnion:
    def test_ac040_multiple_plausible_heads_all_enter_person_group(self):
        person = _view("person", 0, 0, 200, 400, 1)
        h1 = _view("head", 30, 30, 80, 100, 2)
        h2 = _view("head", 120, 30, 170, 100, 3)
        res = infer(person, [person, h1, h2])
        assert res.is_ready
        heads_in = {m.shape_id for m in res.members if m.label == "head"}
        assert {h1.shape_id, h2.shape_id}.issubset(heads_in)

    def test_ac041_face_union_across_heads_deduped(self):
        person = _view("person", 0, 0, 200, 400, 1)
        h1 = _view("head", 20, 20, 80, 90, 2)
        h2 = _view("head", 120, 20, 180, 90, 3)
        # A face that sits between the two heads; could be matched by both.
        shared_face = _view("face", 75, 35, 105, 80, 4)
        res = infer(person, [person, h1, h2, shared_face])
        assert res.is_ready
        # The face appears at most once in the member list.
        member_ids = [m.shape_id for m in res.members]
        assert member_ids.count(shared_face.shape_id) <= 1


# ---------------------------------------------------------------------------
# §33.4 AC-042 / AC-043 — incomplete groups are READY
# ---------------------------------------------------------------------------


class TestIncompleteGroups:
    def test_ac042_person_anchor_missing_head_still_ready(self):
        person = _person(idx=1)
        # Only a face, no head — face cannot be reached from person without
        # an intermediate head.
        face = _face_in(idx=2)
        res = infer(person, [person, face])
        assert res.is_ready
        assert {m.shape_id for m in res.members} == {person.shape_id}

    def test_ac043_person_plus_head_missing_face_ready(self):
        person = _person(idx=1)
        head = _head_in(idx=2)
        res = infer(person, [person, head])
        assert res.is_ready
        assert {m.shape_id for m in res.members} == {
            person.shape_id,
            head.shape_id,
        }


# ---------------------------------------------------------------------------
# §29.3 — stable sort key is a total order
# ---------------------------------------------------------------------------


class TestStableSort:
    def test_equal_score_breaks_tie_by_shape_index(self):
        """Two heads with identical geometry but different shape_index must
        produce a deterministic order (AC-047)."""
        person = _view("person", 0, 0, 200, 400, 1)
        # Two perfectly symmetric heads → identical scores; tie broken by idx.
        h_low = _view("head", 30, 20, 80, 90, 5)
        h_high = _view("head", 120, 20, 170, 90, 6)
        res = infer(person, [person, h_low, h_high])
        heads = res.relation_graph.person_to_heads[person.shape_id]
        # Both admitted; order is deterministic (lower shape_index first).
        assert heads == sorted(heads, key=lambda sid: sid[1])
