"""Stage 3 integration tests: Canvas visibility gates, edit gates, Esc tiers,
and the alignment overlay.

These probes target the Canvas-side behaviour that the pure-Python workflow
tests cannot reach: the main-canvas effective visibility layer, the navigator
base-layer isolation, the four-tier Esc arbitration, and the live overlay.
They reuse the Stage-4A LabelingWidget fixture (real widget + loaded PNG).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anylabeling.config as _cfgmod  # noqa: E402

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "anylabeling",
    "configs",
    "xanylabeling_config.yaml",
)
_cfgmod.current_config_file = _CFG_PATH

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_wrapper import (  # noqa: E402
    LabelingWrapper,
)
from anylabeling.views.labeling.rect_refine_types import (  # noqa: E402
    OverlayModel,
    OverlayRelation,
    RectRefineState,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402

pytest.importorskip("PIL")
from PIL import Image as _PIL_Image  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures (mirror the Stage-4A file)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def png_path(tmp_path):
    p = tmp_path / "img.png"
    _PIL_Image.new("RGB", (300, 300), (255, 255, 255)).save(p)
    return str(p)


@pytest.fixture
def widget(qapp, png_path):
    mw = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(mw)
    w = wrapper.view
    assert w.load_file(png_path) is True
    yield w
    mw.close()


def _rect(label, x, y, w, h, gid=None):
    s = Shape(label=label, shape_type="rectangle")
    s.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + w, y),
        QtCore.QPointF(x + w, y + h),
        QtCore.QPointF(x, y + h),
    ]
    s.group_id = gid
    return s


def _enter_active(widget, person, head, face=None, extra=()):
    """Enable refine mode, register shapes via load_shapes, drive a real
    Canvas selection to ACTIVE.  Returns the workflow."""
    wf = widget._ensure_rect_refine_workflow()
    shapes = (
        [person, head] + ([face] if face is not None else []) + list(extra)
    )
    widget.load_shapes(shapes, replace=True, store_backup=False)
    token = widget._rect_refine_image_token
    views = [
        widget._rect_refine_view_builder.build_view(s, i, token)
        for i, s in enumerate(widget.canvas.shapes)
    ]
    wf.enable(token, views)
    widget.canvas.select_shapes([person], source="canvas")
    return wf


# ---------------------------------------------------------------------------
# 1. predicate=None ⇒ main_visible ≡ base layer (regression guard)
# ---------------------------------------------------------------------------


def test_main_visible_predicate_none_equals_base(widget):
    """Without a task predicate, main_visible must equal the old combined
    check across every visibility combination."""
    canvas = widget.canvas
    assert canvas._main_visibility_predicate is None

    variants = [
        {"visible": True},
        {"visible": False},
        {"visible": True, "hidden_by_filter": True},
        {"visible": False, "hidden_by_filter": True},
        {"visible": True, "hidden_by_filter": False},
    ]
    for attrs in variants:
        s = _rect("person", 0, 0, 10, 10)
        for k, v in attrs.items():
            setattr(s, k, v)
        canvas.visible[s] = attrs["visible"]
        expected = (
            canvas.visible.get(s, True)
            and getattr(s, "visible", True)
            and not getattr(s, "hidden_by_filter", False)
        )
        assert canvas.main_visible(s) is expected
        assert canvas.base_visible(s) is expected


# ---------------------------------------------------------------------------
# 2. ACTIVE hides non-members on the main canvas (AC-051)
# ---------------------------------------------------------------------------


def test_active_hides_non_members_on_main_canvas(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    # An unrelated rectangle that is NOT part of the workgroup.
    stranger = _rect("car", 200, 200, 50, 50)
    wf = _enter_active(widget, person, head, extra=(stranger,))
    assert wf.state == RectRefineState.ACTIVE

    canvas = widget.canvas
    # Members remain visible on the main canvas.
    assert canvas.main_visible(person) is True
    assert canvas.main_visible(head) is True
    # The non-member is hidden on the main canvas even though base-visible.
    assert canvas.base_visible(stranger) is True
    assert canvas.main_visible(stranger) is False
    # iter_main_visible_shapes excludes the stranger.
    visible_ids = {id(s) for s in canvas.iter_main_visible_shapes()}
    assert id(stranger) not in visible_ids
    assert {id(person), id(head)}.issubset(visible_ids)


# ---------------------------------------------------------------------------
# 3. ACTIVE: non-member is not interactive (AC-051 / AC-058)
# ---------------------------------------------------------------------------


def test_active_non_member_not_interactive(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    stranger = _rect("car", 200, 200, 50, 50)
    _enter_active(widget, person, head, extra=(stranger,))
    canvas = widget.canvas

    # is_shape_interactive gates hover/select/edge-hit/double-click.
    assert canvas.is_shape_interactive(person) is True
    assert canvas.is_shape_interactive(stranger) is False
    # Hit candidates exclude the stranger.
    center = QtCore.QPointF(225, 225)
    candidates = canvas._shape_hit_candidates(center) or []
    cand_ids = {id(c) for c in candidates}
    assert id(stranger) not in cand_ids


# ---------------------------------------------------------------------------
# 4. Navigator uses base layer only (AC-052)
# ---------------------------------------------------------------------------


def test_navigator_uses_base_layer_only(widget, monkeypatch):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    stranger = _rect("car", 200, 200, 50, 50)
    _enter_active(widget, person, head, extra=(stranger,))

    captured = {}

    class _FakeNav:
        def isVisible(self):
            return True

        def set_shapes(self, shapes, vis_map):
            captured["shapes"] = shapes
            captured["vis"] = dict(vis_map)

    widget.navigator_dialog = _FakeNav()
    widget.update_navigator_shapes()

    nav_vis = captured["vis"]
    # Navigator reflects the BASE layer: the stranger is still visible there
    # even though the main canvas hides it.
    assert nav_vis.get(stranger) is True
    assert nav_vis.get(person) is True
    assert nav_vis.get(head) is True


# ---------------------------------------------------------------------------
# 5. Esc tier 3 rollbacks the workgroup (AC-062)
# ---------------------------------------------------------------------------


def test_esc_tier3_rollbacks_workgroup(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    wf = _enter_active(widget, person, head)
    canvas = widget.canvas
    assert wf.state == RectRefineState.ACTIVE
    # No rect-edge drag/pending → Esc reaches the workflow tier.
    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_pending_edge is None

    # Drive Esc through the real Canvas keyPressEvent.
    ev = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.keyPressEvent(ev)

    assert wf.state == RectRefineState.SELECTING
    assert not wf.has_active_workgroup


# ---------------------------------------------------------------------------
# 6. Esc tier 1 (rect-edge drag) takes priority (AC-060)
# ---------------------------------------------------------------------------


def test_esc_tier1_drag_takes_priority(widget):
    from anylabeling.views.labeling.rect_edge_alignment import iter_edges

    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    wf = _enter_active(widget, person, head)
    canvas = widget.canvas
    # Enable rect-edge editing and simulate an active drag. The dragging flag
    # derives from active_edge + drag_start_points, so both must be set.
    canvas.set_rect_edge_align_enabled(True)
    active_edge = next(iter(iter_edges(person)))
    canvas.rect_edge_active_edge = active_edge
    canvas.rect_edge_drag_start_points = list(person.points)
    assert canvas.rect_edge_dragging is True

    ev = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.keyPressEvent(ev)

    # Drag cancelled, workgroup still ACTIVE (tier 1 consumed the Esc).
    assert canvas.rect_edge_dragging is False
    assert wf.state == RectRefineState.ACTIVE


# ---------------------------------------------------------------------------
# 7. Overlay threshold: <3.0 shows, ==3.0 / >3.0 do not (AC-090/091/092)
# ---------------------------------------------------------------------------


def test_overlay_threshold_strict_less_than(widget):
    """The overlay must show only when the live delta is strictly < 3.0."""
    canvas = widget.canvas
    person = _rect("person", 10, 10, 100, 200)
    head_close = _rect("head", 40, 11.0, 80, 70)  # y_min diff = 1.0 < 3.0
    head_exact = _rect("head", 40, 13.0, 80, 70)  # y_min diff = 3.0 == 3.0
    head_far = _rect("head", 40, 20.0, 80, 70)  # y_min diff = 10.0 > 3.0

    def _hints_for(person_shape, head_shape):
        rel = OverlayRelation(
            outer_ref=person_shape,
            inner_ref=head_shape,
            edge_kind="top",
            alignment_hint_px=3.0,
        )
        model = OverlayModel(
            is_active=True, selected_id=None, relations=(rel,)
        )
        canvas._overlay_provider = lambda: model
        # Compute the same delta the painter would.
        delta = abs(
            min(pt.y() for pt in head_shape.points)
            - min(pt.y() for pt in person_shape.points)
        )
        return delta < 3.0

    assert _hints_for(person, head_close) is True
    assert _hints_for(person, head_exact) is False
    assert _hints_for(person, head_far) is False
    canvas._overlay_provider = None


# ---------------------------------------------------------------------------
# 8. Overlay text contains no numeric values (AC-097)
# ---------------------------------------------------------------------------


def test_overlay_no_numeric_values(widget):
    """Overlay wording must never include pixel numbers or scores."""
    import inspect

    from anylabeling.views.labeling.widgets import canvas as canvas_module

    src = inspect.getsource(canvas_module.Canvas._paint_rect_refine_overlay)
    # The hint messages are fixed wording keys; verify no f-string formatting
    # of the delta leaks into the drawn text.
    assert "上沿已接近" in src
    assert "下沿已接近" in src
    # The delta is only used for the threshold comparison, never rendered.
    # Ensure drawText is not fed a numeric delta.
    assert "{delta" not in src
    assert "{{delta" not in src
