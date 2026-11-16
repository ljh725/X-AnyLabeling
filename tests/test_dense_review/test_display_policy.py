"""Pure display-resolution rules for the dense-review workbench.

These tests assert the decision table only: which role a shape gets, which
components stay on, and which exclusions win.  Nothing here paints or mutates
the canvas, which is exactly the property D2 relies on (DP-01, DP-02, DP-11,
DP-12, DP-15, DP-17, DP-18).
"""

import pytest

from anylabeling.services.dense_review.display import (
    PAINT_ORDER,
    REASON_FILTERED,
    REASON_GLOBAL_OFF,
    REASON_LABEL_HIDDEN,
    REASON_MANUAL_HIDDEN,
    REASON_MISSING,
    REASON_ORIGINAL_ONLY,
    ROLE_BATCH,
    ROLE_CURRENT,
    ROLE_OTHER,
    DisplayContext,
    RoleStyle,
    default_role_styles,
    exclusion_summary,
    paint_groups,
    resolve_all,
    resolve_shape,
)


class _Shape:
    def __init__(self, shape_id, label):
        self.xanylabeling_shape_id = shape_id
        self.label = label


def _context(**overrides):
    values = dict(
        batch_ids=frozenset({"id1", "id2"}),
        current_id="id1",
        associated_ids=frozenset(),
    )
    values.update(overrides)
    return DisplayContext(**values)


def test_roles_default_fill_to_zero_and_scale_by_role():
    styles = default_role_styles()
    assert styles[ROLE_CURRENT].fill == 0.0
    assert styles[ROLE_BATCH].fill == 0.0
    assert styles[ROLE_OTHER].fill == 0.0
    # Current > batch > other on every graded component (DP-01).
    for component in ("outline", "points", "text", "attributes"):
        current = getattr(styles[ROLE_CURRENT], component)
        batch = getattr(styles[ROLE_BATCH], component)
        other = getattr(styles[ROLE_OTHER], component)
        assert current >= batch >= other
    # Handles belong to the current object only (DP-03).
    assert styles[ROLE_CURRENT].handles > 0.0
    assert styles[ROLE_BATCH].handles == 0.0
    assert styles[ROLE_OTHER].handles == 0.0
    # Other objects drop their text but keep a recognisable outline.
    assert styles[ROLE_OTHER].text == 0.0
    assert styles[ROLE_OTHER].outline > 0.0


def test_role_assignment_covers_current_batch_and_other():
    context = _context()
    current = resolve_shape("id1", "person", context)
    batch = resolve_shape("id2", "person", context)
    other = resolve_shape("id9", "car", context)
    assert current.role == ROLE_CURRENT
    assert batch.role == ROLE_BATCH
    assert other.role == ROLE_OTHER
    assert current.style.handles > 0.0
    assert batch.style.handles == 0.0


def test_associated_keypoint_follows_current_rectangle():
    context = _context(associated_ids=frozenset({"kp1"}))
    display = resolve_shape("kp1", "nose", context)
    assert display.role == ROLE_CURRENT
    assert display.style.points > 0.0


def test_global_off_and_original_only_stop_paint_and_hit():
    shape = "id1"
    for overrides, reason in (
        ({"global_annotations_on": False}, REASON_GLOBAL_OFF),
        ({"original_only": True}, REASON_ORIGINAL_ONLY),
    ):
        display = resolve_shape(shape, "person", _context(**overrides))
        assert display.drawable is False
        assert display.hittable is False
        assert display.label_visible is False
        assert display.reason == reason


def test_manual_hide_and_filters_exclude_but_explain():
    for overrides, reason in (
        ({"manual_hidden": frozenset({"id1"})}, REASON_MANUAL_HIDDEN),
        ({"label_hidden": frozenset({"id1"})}, REASON_LABEL_HIDDEN),
        ({"filtered": frozenset({"id1"})}, REASON_FILTERED),
    ):
        display = resolve_shape("id1", "person", _context(**overrides))
        assert display.drawable is False
        assert display.reason == reason


def test_temporary_show_lifts_only_user_exclusions():
    # A manual hide lifted by an explicit temporary show (DP-11).
    display = resolve_shape(
        "id1",
        "person",
        _context(
            manual_hidden=frozenset({"id1"}),
            temporary_ids=frozenset({"id1"}),
        ),
    )
    assert display.drawable is True
    assert display.temporary is True
    assert display.reason == ""

    # The exception is exact: a sibling stays hidden.
    sibling = resolve_shape(
        "id2",
        "person",
        _context(
            manual_hidden=frozenset({"id2"}),
            temporary_ids=frozenset({"id1"}),
        ),
    )
    assert sibling.drawable is False

    # Global-off still wins over the exception (DP-12).
    off = resolve_shape(
        "id1",
        "person",
        _context(
            manual_hidden=frozenset({"id1"}),
            temporary_ids=frozenset({"id1"}),
            global_annotations_on=False,
        ),
    )
    assert off.drawable is False
    assert off.reason == REASON_GLOBAL_OFF

    # So does original-only comparison (DP-12).
    original = resolve_shape(
        "id1",
        "person",
        _context(
            filtered=frozenset({"id1"}),
            temporary_ids=frozenset({"id1"}),
            original_only=True,
        ),
    )
    assert original.drawable is False
    assert original.reason == REASON_ORIGINAL_ONLY


def test_zero_strength_role_removes_paint_and_hit_together():
    zero = RoleStyle(
        fill=0.0,
        outline=0.0,
        outline_width=1.0,
        points=0.0,
        handles=0.0,
        text=0.0,
        text_plate=0.0,
        attributes=0.0,
        linking=0.0,
        mask=0.0,
    )
    context = _context(styles={ROLE_OTHER: zero})
    display = resolve_shape("id9", "car", context)
    # The shape parses fine and has no exclusion reason, yet no component
    # paints, so it must not be hittable either (DP-02).
    assert display.reason == ""
    assert display.drawable is False
    assert display.hittable is False
    assert display.label_visible is False


def test_point_only_style_stays_hittable_without_handles():
    point_only = RoleStyle(
        fill=0.0,
        outline=0.0,
        outline_width=1.0,
        points=0.8,
        handles=0.0,
        text=0.0,
        text_plate=0.0,
        attributes=0.0,
        linking=0.0,
        mask=0.0,
    )
    context = _context(styles={ROLE_OTHER: point_only})
    display = resolve_shape("id9", "nose", context)
    assert display.drawable is True
    assert display.hittable is True


def test_unsupported_shapes_stay_visible_but_outside_review_range():
    context = _context(unsupported=frozenset({"id5"}))
    unsupported = resolve_shape("id5", "nose", context)
    # A keypoint (or any unsupported shape) has to stay observable and
    # editable; only the formal confirmation range excludes it (PC-03).
    assert unsupported.drawable is True
    assert unsupported.hittable is True
    assert unsupported.reason == ""
    assert unsupported.reviewable is False

    supported = resolve_shape("id1", "person", _context())
    assert supported.reviewable is True

    resolved = resolve_all(
        [_Shape("id1", "person")],
        context,
        shape_id_of=lambda item: item.xanylabeling_shape_id,
        label_of=lambda item: item.label,
    )
    assert set(resolved) == {"id1"}


def test_paint_order_is_other_batch_current():
    assert PAINT_ORDER == (ROLE_OTHER, ROLE_BATCH, ROLE_CURRENT)
    displays = resolve_all(
        [_Shape("id1", "a"), _Shape("id2", "a"), _Shape("id9", "b")],
        _context(),
        shape_id_of=lambda item: item.xanylabeling_shape_id,
        label_of=lambda item: item.label,
    )
    groups = paint_groups(displays)
    assert [role for role, _ in groups] == [
        ROLE_OTHER,
        ROLE_BATCH,
        ROLE_CURRENT,
    ]
    assert groups[0][1] == ["id9"]
    assert groups[-1][1] == ["id1"]


def test_exclusion_summary_counts_reasons():
    displays = resolve_all(
        [_Shape("id1", "a"), _Shape("id2", "a"), _Shape("id9", "b")],
        _context(
            manual_hidden=frozenset({"id1"}),
            filtered=frozenset({"id9"}),
        ),
        shape_id_of=lambda item: item.xanylabeling_shape_id,
        label_of=lambda item: item.label,
    )
    summary = exclusion_summary(displays)
    assert summary[REASON_MANUAL_HIDDEN] == 1
    assert summary[REASON_FILTERED] == 1
    assert summary.get(REASON_MISSING, 0) == 0


def test_role_style_normalizes_out_of_range_values():
    style = RoleStyle.from_dict(
        {"fill": 5.0, "outline": -1.0, "outline_width": 99.0, "text": "0.5"}
    )
    assert style.fill == 1.0
    assert style.outline == 0.0
    assert style.outline_width == 6.0
    assert style.text == 0.5

    # Invalid strings fall back to defaults instead of raising.
    fallback = RoleStyle.from_dict({"outline": "opaque"})
    assert fallback.outline == RoleStyle().outline


def test_locked_object_stays_visible_and_marked():
    display = resolve_shape("id1", "person", _context(), locked=True)
    assert display.drawable is True
    assert display.locked is True
    assert display.style.handles > 0.0


def test_hover_does_not_change_the_current_object():
    context = _context(hovering_id="id2")
    resolved = resolve_shape("id2", "person", context)
    # Hover is presentation only; role and target stay with the session
    # (DP-09, DP-10).
    assert resolved.role == ROLE_BATCH
    assert context.current_id == "id1"
    assert "hovering_id" in {field for field in context.__dict__}
