"""Tests for Feature 2: DigitBindDrawManager (task 7.4-7.8, 7.14, 7.15, 7.18).

Pure unit tests: the manager is a plain object, so we mock the host
``label_widget`` with ``types.SimpleNamespace``. No QApplication needed
for the core logic tests (status/tr are stubbed).
"""

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from anylabeling.views.labeling.widgets.digit_bind_draw_manager import (  # noqa: E402
    BindCommitStatus,
    BindPendingContext,
    DigitBindDrawManager,
)
from tests.conftest import MockShape  # noqa: E402


def _make_label_widget(
    shortcuts=None,
    selected=None,
    shapes=None,
    config_mode="bind_draw",
    auto_person_instance=False,
):
    """Build a minimal label_widget stand-in for manager tests."""
    lw = types.SimpleNamespace()
    lw._config = {
        "digit_shortcut_mode": config_mode,
        "auto_person_instance": auto_person_instance,
    }
    lw.digit_to_label = None
    lw.drawing_digit_shortcuts = shortcuts or {}
    lw.status = lambda *a, **k: None
    lw.tr = lambda x: x
    lw.toggle_draw_mode = lambda **k: None

    # digit_page_manager.get_actual_index default identity.
    lw.digit_page_manager = types.SimpleNamespace(get_actual_index=lambda d: d)

    # canvas with selected_shapes, shapes, gen_new_group_id.
    canvas = types.SimpleNamespace()
    canvas.selected_shapes = selected or []
    canvas.shapes = shapes if shapes is not None else (selected or [])

    def gen_new_group_id():
        existing = [
            s.group_id for s in canvas.shapes if s.group_id is not None
        ]
        return (max(existing) + 1) if existing else 1

    canvas.gen_new_group_id = gen_new_group_id
    lw.canvas = canvas
    return lw


def _person(gid=None):
    return MockShape(label="person", shape_type="rectangle", group_id=gid)


def _head(gid=None):
    return MockShape(label="head", shape_type="rectangle", group_id=gid)


def _face(gid=None):
    return MockShape(label="face", shape_type="rectangle", group_id=gid)


# ----------------------------------------------------------------------
# task 7.4: inherit group_id from source
# ----------------------------------------------------------------------
def test_7_4_inherits_group_id_from_source():
    """bind_draw from a source that already has group_id inherits it."""
    source = _person(gid=7)
    lw = _make_label_widget(
        shortcuts={1: {"label": "head", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)

    handled = mgr.handle_digit(1)

    assert handled is True
    assert mgr.pending is not None
    assert mgr.pending.gid == 7
    assert mgr.pending.need_backfill is False
    assert mgr.pending.target_label == "head"
    # Source group_id must NOT be touched at handle time.
    assert source.group_id == 7


# ----------------------------------------------------------------------
# task 7.5: source without group_id -> mint + lazy backfill flag
# ----------------------------------------------------------------------
def test_7_5_source_without_gid_mints_and_flags_backfill():
    """Source without group_id: mint a new gid, flag need_backfill,
    but do NOT write the source at handle time (lazy)."""
    source = _head(gid=None)
    lw = _make_label_widget(
        shortcuts={2: {"label": "person", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)

    mgr.handle_digit(2)

    assert mgr.pending is not None
    assert mgr.pending.gid == 1  # first gid
    assert mgr.pending.need_backfill is True
    # Lazy: source still has no group_id at handle time.
    assert source.group_id is None

    result = mgr.consume_pending()
    assert result.status is BindCommitStatus.READY
    assert result.context.target_label == "person"
    assert result.context.gid == 1
    assert result.context.source is source
    assert result.context.need_backfill is True


def test_7_5_consume_then_clear_drops_pending():
    """After consume_pending, a second consume returns None (the caller
    is responsible for clear_pending after writing). Explicit clear also
    works and leaves source untouched."""
    source = _head(gid=None)
    lw = _make_label_widget(
        shortcuts={2: {"label": "person", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(2)

    first = mgr.consume_pending()
    assert first.status is BindCommitStatus.READY
    # Pending still present until cleared (caller writes, then clears).
    assert mgr.pending is not None
    mgr.clear_pending()
    assert mgr.pending is None
    # Source never written.
    assert source.group_id is None


# ----------------------------------------------------------------------
# task 7.6: duplicate target label in group -> reject
# ----------------------------------------------------------------------
def test_7_6_duplicate_target_label_rejected():
    """If the group already has the target label, reject before entering
    draw mode (no pending created)."""
    existing_person = _person(gid=3)
    source = _head(gid=3)
    lw = _make_label_widget(
        shortcuts={1: {"label": "person", "mode": "rectangle"}},
        selected=[source],
        shapes=[existing_person, source],
    )
    mgr = DigitBindDrawManager(lw)

    mgr.handle_digit(1)

    assert (
        mgr.pending is None
    ), "must not enter draw mode when group already has target label"


def test_7_6b_duplicate_check_at_consume_toctou():
    """Second duplicate check at consume_pending catches a duplicate
    created between handle_digit and consume (TOCTOU guard)."""
    source = _head(gid=5)
    lw = _make_label_widget(
        shortcuts={1: {"label": "person", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is not None

    # Simulate another tool adding a person to group 5 mid-draw.
    lw.canvas.shapes.append(_person(gid=5))

    result = mgr.consume_pending()
    assert result.status is BindCommitStatus.REJECTED
    assert mgr.pending is None


# ----------------------------------------------------------------------
# task 7.7: multi-selection source rejected
# ----------------------------------------------------------------------
def test_7_7_multi_selection_source_rejected():
    """Multi-selection source must be rejected (v0 single-source only)."""
    s1 = _person(gid=1)
    s2 = _head(gid=2)
    lw = _make_label_widget(
        shortcuts={1: {"label": "face", "mode": "rectangle"}},
        selected=[s1, s2],
        shapes=[s1, s2],
    )
    mgr = DigitBindDrawManager(lw)

    mgr.handle_digit(1)

    assert mgr.pending is None


def test_7_7b_no_source_rejected():
    """No selection -> reject."""
    lw = _make_label_widget(
        shortcuts={1: {"label": "face", "mode": "rectangle"}},
        selected=[],
        shapes=[],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is None


def test_no_source_person_digit_starts_auto_person_instance_draw():
    """No selection can start Feature 1 when the digit maps to person."""
    captured = {}
    lw = _make_label_widget(
        shortcuts={1: {"label": "person", "mode": "rectangle"}},
        selected=[],
        shapes=[],
        auto_person_instance=True,
    )
    lw.toggle_draw_mode = lambda **kwargs: captured.update(kwargs)
    mgr = DigitBindDrawManager(lw)

    handled = mgr.handle_digit(1)

    assert handled is True
    assert mgr.pending is None
    assert lw.digit_to_label == "person"
    assert captured == {"edit": False, "create_mode": "rectangle"}


def test_no_source_head_digit_still_requires_bind_source():
    """Feature 1 exception only applies to person rectangles."""
    captured = {}
    lw = _make_label_widget(
        shortcuts={1: {"label": "head", "mode": "rectangle"}},
        selected=[],
        shapes=[],
        auto_person_instance=True,
    )
    lw.toggle_draw_mode = lambda **kwargs: captured.update(kwargs)
    mgr = DigitBindDrawManager(lw)

    mgr.handle_digit(1)

    assert mgr.pending is None
    assert lw.digit_to_label is None
    assert captured == {}


def test_7_7c_bad_source_label_rejected():
    """Source label not in person/head/face -> reject."""
    car = MockShape(label="car", shape_type="rectangle")
    lw = _make_label_widget(
        shortcuts={1: {"label": "face", "mode": "rectangle"}},
        selected=[car],
        shapes=[car],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is None


def test_7_7d_bad_source_shape_type_rejected():
    """Source shape_type != rectangle -> reject."""
    polygon_person = MockShape(label="person", shape_type="polygon")
    lw = _make_label_widget(
        shortcuts={1: {"label": "face", "mode": "rectangle"}},
        selected=[polygon_person],
        shapes=[polygon_person],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is None


# ----------------------------------------------------------------------
# task 7.8: hint content covers mode/source/digit/target/action
# ----------------------------------------------------------------------
def test_7_8_hint_fires_on_success_and_records_status():
    """A successful handle_digit emits a status hint that includes the
    digit, source label, gid, and target label."""
    source = _person(gid=9)
    captured = []
    lw = _make_label_widget(
        shortcuts={3: {"label": "head", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    lw.status = lambda msg, delay=2500: captured.append((msg, delay))
    mgr = DigitBindDrawManager(lw)

    mgr.handle_digit(3)

    assert len(captured) >= 1
    msg, _delay = captured[-1]
    # The hint should reference the digit, source label, gid, target.
    assert "3" in msg
    assert "person" in msg
    assert "9" in msg
    assert "head" in msg


# ----------------------------------------------------------------------
# task 3.7/3.8: invalid target (non-rectangle or non-bind label)
# ----------------------------------------------------------------------
def test_invalid_target_non_bind_label_rejected():
    """A digit mapping whose target label is not person/head/face is
    rejected (e.g. mapping to 'car')."""
    source = _person(gid=1)
    lw = _make_label_widget(
        shortcuts={1: {"label": "car", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is None


def test_invalid_target_non_rectangle_rejected():
    """A digit mapping whose target shape_type is not rectangle is
    rejected."""
    source = _person(gid=1)
    lw = _make_label_widget(
        shortcuts={1: {"label": "head", "mode": "polygon"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is None


def test_unmapped_digit_rejected():
    """A digit with no mapping is rejected with a hint."""
    source = _person(gid=1)
    lw = _make_label_widget(
        shortcuts={},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(5)
    assert mgr.pending is None


# ----------------------------------------------------------------------
# task 7.15: Esc / clear_pending leaves source group_id unchanged
# ----------------------------------------------------------------------
def test_7_15_clear_pending_leaves_source_untouched():
    """After handle_digit mints a gid, clear_pending (Esc/cancel) must
    NOT have written the source group_id (lazy backfill guarantee)."""
    source = _head(gid=None)
    lw = _make_label_widget(
        shortcuts={2: {"label": "person", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(2)
    assert mgr.pending is not None
    assert mgr.pending.need_backfill is True

    mgr.clear_pending()

    assert mgr.pending is None
    assert lw.digit_to_label is None
    assert (
        source.group_id is None
    ), "clear_pending must not backfill the source"


# ----------------------------------------------------------------------
# task 7.14: undo atomicity — backfill + new shape in one snapshot
# (verified at the manager contract level: consume returns the tuple
#  BEFORE set_last_label so the caller writes both in one transaction)
# ----------------------------------------------------------------------
def test_7_14_consume_returns_backfill_before_commit():
    """consume_pending returns (label, gid, source, need_backfill) so
    the caller can backfill the source and create the new shape in the
    same undo snapshot (D2: backfill before set_last_label).

    This test verifies the contract: the returned tuple carries the
    source reference and backfill flag, and the source is still
    un-modified at consume time (caller does the write)."""
    source = _head(gid=None)
    lw = _make_label_widget(
        shortcuts={2: {"label": "person", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(2)

    result = mgr.consume_pending()

    assert result.status is BindCommitStatus.READY
    assert result.context.target_label == "person"
    assert result.context.gid == 1
    assert result.context.source is source
    assert result.context.need_backfill is True
    # Source still un-modified: caller writes it next to the new shape.
    assert source.group_id is None


# ----------------------------------------------------------------------
# task 7.18: pending期间 mode互斥 (manager-level: pending active blocks
# re-entry)
# ----------------------------------------------------------------------
def test_7_18_pending_active_blocks_reentry():
    """While a bind is pending, a second digit is rejected (no stacking)."""
    source = _person(gid=1)
    lw = _make_label_widget(
        shortcuts={1: {"label": "head", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    assert mgr.pending is not None

    # Second digit while pending -> rejected, pending unchanged.
    mgr.handle_digit(2)
    assert mgr.pending.target_label == "head"


# ----------------------------------------------------------------------
# is_active gate
# ----------------------------------------------------------------------
def test_is_active_only_in_bind_draw_mode():
    """is_active reflects the digit_shortcut_mode config."""
    lw_on = _make_label_widget(config_mode="bind_draw")
    lw_off = _make_label_widget(config_mode="rename")
    assert DigitBindDrawManager(lw_on).is_active() is True
    assert DigitBindDrawManager(lw_off).is_active() is False


def test_invalid_source_group_id_is_rejected_without_crash():
    """A malformed source group ID must not be coerced or crash binding."""
    source = _person(gid="7")
    lw = _make_label_widget(
        shortcuts={1: {"label": "head", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)

    assert mgr.handle_digit(1) is True
    assert mgr.pending is None
    assert lw.digit_to_label is None


def test_source_group_id_change_rejects_final_commit():
    """A source changed during drawing must reject the target commit."""
    source = _person(gid=4)
    lw = _make_label_widget(
        shortcuts={1: {"label": "head", "mode": "rectangle"}},
        selected=[source],
        shapes=[source],
    )
    mgr = DigitBindDrawManager(lw)
    mgr.handle_digit(1)
    source.group_id = 5

    result = mgr.consume_pending()

    assert result.status is BindCommitStatus.REJECTED
    assert mgr.pending is None
    assert lw.digit_to_label is None


def test_consume_without_pending_has_explicit_status():
    """No pending bind is distinct from a rejected pending bind."""
    lw = _make_label_widget()
    result = DigitBindDrawManager(lw).consume_pending()
    assert result.status is BindCommitStatus.NO_PENDING
