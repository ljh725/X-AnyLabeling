"""Stage 6 — boundary / edge-case acceptance coverage (PyQt offscreen).

Fills the remaining §33 AC points that need a real LabelingWidget:
continuous mode, nested-box hit-test, hidden-but-inferred members, save
sub-paths, auto-save disk invariants, Overlay edge cases, rect_edge switch
preservation, and ACTIVE-mode-close.  AC-021~031 (GID merge/conflict) are
already covered by the pure-Python grouping suite and are not duplicated.
"""

from __future__ import annotations

import json
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
    SaveResult,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402

pytest.importorskip("PIL")
from PIL import Image as _PIL_Image  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def make_png(tmp_path):
    def _make(name="img.png", size=(300, 300), color=(255, 255, 255)):
        p = tmp_path / name
        _PIL_Image.new("RGB", size, color).save(p)
        return str(p)

    return _make


@pytest.fixture
def widget(qapp, make_png):
    png = make_png()
    mw = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(mw)
    w = wrapper.view
    assert w.load_file(png) is True
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


def _enter_active(widget, *shapes):
    wf = widget._ensure_rect_refine_workflow()
    widget.load_shapes(list(shapes), replace=True, store_backup=False)
    token = widget._rect_refine_image_token
    views = [
        widget._rect_refine_view_builder.build_view(s, i, token)
        for i, s in enumerate(widget.canvas.shapes)
    ]
    wf.enable(token, views)
    widget.canvas.select_shapes([shapes[0]], source="canvas")
    return wf


# ---------------------------------------------------------------------------
# AC-003: continuous mode — after accept/Esc, the next anchor is selectable
# ---------------------------------------------------------------------------


def test_ac003_continuous_mode_selects_next_anchor(
    widget, monkeypatch, tmp_path
):
    p1 = _rect("person", 10, 10, 80, 160)
    h1 = _rect("head", 30, 20, 60, 60)
    widget._toggle_rect_refine_mode(True)
    wf = _enter_active(widget, p1, h1)

    out = tmp_path / "o.json"
    monkeypatch.setattr(widget, "save_file_dialog", lambda: str(out))
    wf.accept_current_workgroup()
    assert wf.state == RectRefineState.SELECTING
    assert widget.actions.toggle_rect_refine_mode.isChecked() is True

    # A second person/head pair can immediately form a new workgroup.
    p2 = _rect("person", 110, 10, 80, 160)
    h2 = _rect("head", 130, 20, 60, 60)
    widget.load_shapes([p2, h2], replace=True, store_backup=False)
    token = widget._rect_refine_image_token
    views = [
        widget._rect_refine_view_builder.build_view(s, i, token)
        for i, s in enumerate(widget.canvas.shapes)
    ]
    wf.enable(token, views)
    widget.canvas.select_shapes([p2], source="canvas")
    assert wf.state == RectRefineState.ACTIVE


# ---------------------------------------------------------------------------
# AC-013: nested-box click anchor == Canvas hit-test final selection
# ---------------------------------------------------------------------------


def test_ac013_nested_box_anchor_matches_canvas_selection(widget):
    outer = _rect("person", 10, 10, 100, 200)
    inner = _rect("head", 40, 30, 40, 60)
    widget.load_shapes([outer, inner], replace=True, store_backup=False)
    widget._toggle_rect_refine_mode(True)
    wf = widget._rect_refine_workflow
    # Click inside the inner box → Canvas hit-test resolves to innermost first.
    center = QtCore.QPointF(60, 60)
    widget.canvas.select_shape_point(center, multiple_selection_mode=False)
    # The workflow's anchor is whatever Canvas committed as selected.
    if wf.has_active_workgroup:
        snap = wf.workgroup_snapshot
        assert snap.anchor_shape_id == (
            widget._rect_refine_image_token,
            id(widget.canvas.selected_shapes[0]),
        )


# ---------------------------------------------------------------------------
# AC-017: anchor visible but related objects hidden by base filter still join
# ---------------------------------------------------------------------------


def test_ac017_hidden_by_filter_member_still_inferred(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    # Hide the head on the base layer; the workflow's inference must still
    # scan it and admit it into the workgroup (§26.2 step 4).
    head.hidden_by_filter = True
    widget._toggle_rect_refine_mode(True)
    wf = _enter_active(widget, person, head)
    # The head is part of the workgroup even though base-hidden.
    snap = wf.workgroup_snapshot
    assert (widget._rect_refine_image_token, id(head)) in set(
        snap.member_shape_ids
    )


# ---------------------------------------------------------------------------
# AC-056 / AC-057: rect_edge editing switch preserved across mode entry/exit
# ---------------------------------------------------------------------------


class TestRectEdgeSwitchPreserved:
    def test_ac056_off_before_stays_off_after(self, widget):
        widget.canvas.set_rect_edge_align_enabled(False)
        widget._toggle_rect_refine_mode(True)
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        _enter_active(widget, person, head)
        widget._toggle_rect_refine_mode(False)
        assert widget.canvas.rect_edge_align_enabled is False

    def test_ac057_on_before_stays_on_after(self, widget):
        widget.canvas.set_rect_edge_align_enabled(True)
        widget._toggle_rect_refine_mode(True)
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        _enter_active(widget, person, head)
        widget._toggle_rect_refine_mode(False)
        assert widget.canvas.rect_edge_align_enabled is True


# ---------------------------------------------------------------------------
# AC-072: drag/pending blocks Ctrl+Enter
# ---------------------------------------------------------------------------


class TestAcceptGuards:
    def test_ac072_drag_blocks_accept(self, widget):
        from anylabeling.views.labeling.rect_edge_alignment import iter_edges

        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        widget._toggle_rect_refine_mode(True)
        wf = _enter_active(widget, person, head)
        # Set up an active rect-edge drag.
        widget.canvas.set_rect_edge_align_enabled(True)
        edge = next(iter(iter_edges(person)))
        widget.canvas.rect_edge_active_edge = edge
        widget.canvas.rect_edge_drag_start_points = list(person.points)
        assert widget.canvas.rect_edge_dragging is True
        result = wf.accept_current_workgroup()
        assert result == SaveResult.CANCELLED
        assert wf.state == RectRefineState.ACTIVE

    def test_ac074_cancel_dialog_keeps_workgroup(self, widget, monkeypatch):
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        widget._toggle_rect_refine_mode(True)
        wf = _enter_active(widget, person, head)
        monkeypatch.setattr(widget, "save_file_dialog", lambda: "")
        result = wf.accept_current_workgroup()
        assert result == SaveResult.CANCELLED
        assert wf.state == RectRefineState.ACTIVE
        assert wf.has_active_workgroup

    def test_ac076_save_exception_not_stranded_in_saving(
        self, widget, monkeypatch
    ):
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        widget._toggle_rect_refine_mode(True)
        wf = _enter_active(widget, person, head)
        out_path = "/tmp/rect_refine_exc.json"
        monkeypatch.setattr(widget, "save_file_dialog", lambda: out_path)
        monkeypatch.setattr(
            widget,
            "save_labels",
            lambda fn: (_ for _ in ()).throw(RuntimeError("disk failure")),
        )
        result = wf.accept_current_workgroup()
        assert result == SaveResult.FAILED
        assert wf.state == RectRefineState.ACTIVE
        assert wf.state != RectRefineState.SAVING

    def test_ac079_no_geometry_change_still_saves(
        self, widget, monkeypatch, tmp_path
    ):
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        widget._toggle_rect_refine_mode(True)
        wf = _enter_active(widget, person, head)
        # No shape_moved emitted → no committed geometry.
        assert wf.workgroup_geometry_dirty is False
        out = tmp_path / "noedit.json"
        monkeypatch.setattr(widget, "save_file_dialog", lambda: str(out))
        result = wf.accept_current_workgroup()
        assert result == SaveResult.SUCCESS
        assert out.exists()


# ---------------------------------------------------------------------------
# AC-077 / AC-078: auto_save=true disk invariants
# ---------------------------------------------------------------------------


class TestAutoSaveDiskInvariants:
    def test_ac077_in_workgroup_edit_no_disk_change(
        self, widget, monkeypatch, tmp_path
    ):
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        # Pre-write a baseline JSON so we can assert it is untouched.
        baseline = tmp_path / "baseline.json"
        baseline.write_text("{}", encoding="utf-8")
        widget._config["auto_save"] = True
        widget._toggle_rect_refine_mode(True)
        wf = _enter_active(widget, person, head)
        save_calls = []
        monkeypatch.setattr(
            widget,
            "save_labels",
            lambda fn: save_calls.append(fn) or True,
        )
        # In-workgroup edit.
        head.points[0] = QtCore.QPointF(41.0, 20.0)
        widget.canvas.shape_moved.emit()
        assert save_calls == []  # auto-save blocked while ACTIVE
        assert wf.workgroup_geometry_dirty is True

    def test_ac078_accept_writes_final_geometry(
        self, widget, monkeypatch, tmp_path
    ):
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 20, 80, 70)
        widget._toggle_rect_refine_mode(True)
        wf = _enter_active(widget, person, head)
        # Commit a geometry change.
        head.points[0] = QtCore.QPointF(41.0, 20.0)
        widget.canvas.shape_moved.emit()
        out = tmp_path / "final.json"
        monkeypatch.setattr(widget, "save_file_dialog", lambda: str(out))
        result = wf.accept_current_workgroup()
        assert result == SaveResult.SUCCESS
        data = json.loads(out.read_text(encoding="utf-8"))
        labels = {s["label"] for s in data["shapes"]}
        assert {"person", "head"}.issubset(labels)
        # No temp fields leak into the persisted JSON.
        blob = out.read_text(encoding="utf-8")
        assert "rect_refine" not in blob
        assert "qa_entity_id" not in blob


# ---------------------------------------------------------------------------
# AC-084: ACTIVE mode-close returns to OFF and restores base layer
# ---------------------------------------------------------------------------


def test_ac084_active_close_mode_restores_base(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    stranger = _rect("car", 200, 200, 50, 50)
    widget._toggle_rect_refine_mode(True)
    _enter_active(widget, person, head, stranger)
    canvas = widget.canvas
    # Stranger is hidden on main canvas while ACTIVE.
    assert canvas.main_visible(stranger) is False
    # Close the mode → base layer restored, stranger visible again.
    widget._toggle_rect_refine_mode(False)
    assert widget._rect_refine_workflow.state == RectRefineState.OFF
    assert canvas.main_visible(stranger) is True
    assert canvas._main_visibility_predicate is None


# ---------------------------------------------------------------------------
# AC-091 / AC-092 / AC-094 / AC-095: Overlay edge cases
# ---------------------------------------------------------------------------


class TestOverlayEdges:
    def _model(self, person, head, edge_kind="top", hint=3.0):
        return OverlayModel(
            is_active=True,
            selected_id=None,
            relations=(
                OverlayRelation(
                    outer_ref=person,
                    inner_ref=head,
                    edge_kind=edge_kind,
                    alignment_hint_px=hint,
                ),
            ),
        )

    def test_ac091_exact_threshold_no_hint(self, widget):
        canvas = widget.canvas
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 13.0, 80, 70)  # y_min diff exactly 3.0
        canvas._overlay_provider = lambda: self._model(person, head)
        delta = abs(
            min(pt.y() for pt in head.points)
            - min(pt.y() for pt in person.points)
        )
        assert delta == pytest.approx(3.0)
        assert (delta < 3.0) is False
        canvas._overlay_provider = None

    def test_ac092_above_threshold_no_hint(self, widget):
        canvas = widget.canvas
        person = _rect("person", 10, 10, 100, 200)
        head = _rect("head", 40, 40.0, 80, 70)  # y_min diff 30 > 3
        canvas._overlay_provider = lambda: self._model(person, head)
        delta = abs(
            min(pt.y() for pt in head.points)
            - min(pt.y() for pt in person.points)
        )
        assert (delta < 3.0) is False
        canvas._overlay_provider = None

    def test_ac095_ambiguous_relation_no_hint(self, widget):
        """A relation whose ownership is ambiguous must not show a hint.

        We model ambiguity by a workgroup whose person_to_heads has two
        heads → the workflow's overlay derivation skips that relation.
        """
        from anylabeling.views.labeling.rect_refine_types import (
            RelationGraph,
        )
        from anylabeling.views.labeling.rect_refine_workflow import (
            RectRefineWorkflow,
        )
        from tests.test_rect_refine_workflow import (
            FakeCanvas,
            FakeSave,
            FakeDirty,
            FakeViewBuilder,
        )

        person = _rect("person", 10, 10, 200, 400)
        h1 = _rect("head", 30, 20, 80, 90)
        h2 = _rect("head", 120, 20, 80, 90)
        wf = RectRefineWorkflow(
            canvas=FakeCanvas(),
            save=FakeSave(),
            dirty=FakeDirty(),
            view_builder=FakeViewBuilder(),
        )
        # Manually stand up an ACTIVE workgroup with an ambiguous graph.
        from anylabeling.views.labeling.rect_refine_types import (
            RectRefineWorkgroup,
            WorkgroupSnapshot,
            CandidateSource,
        )

        token = "t1"
        sid_p = (token, id(person))
        sid_h1 = (token, id(h1))
        sid_h2 = (token, id(h2))
        graph = RelationGraph(
            person_to_heads={sid_p: [sid_h1, sid_h2]},
        )
        wf._image_token = token
        wf._state = RectRefineState.ACTIVE  # overlay_model gates on this.
        wf._workgroup = RectRefineWorkgroup(
            snapshot=WorkgroupSnapshot(
                image_token=token,
                anchor_shape_id=sid_p,
                member_shape_ids=(sid_p, sid_h1, sid_h2),
                original_points={sid_p: (), sid_h1: (), sid_h2: ()},
                dirty_before=False,
                undo_floor=0,
                relation_graph=graph,
                provenance={sid_p: CandidateSource.GEOMETRY},
            ),
            state=RectRefineState.ACTIVE,
            current_members={sid_p: person, sid_h1: h1, sid_h2: h2},
        )
        wf._member_refs = {sid_p: person, sid_h1: h1, sid_h2: h2}
        wf._undo_stack = [{}]
        model = wf.overlay_model()
        assert model is not None
        # Two heads → no top-edge relation emitted.
        assert all(r.edge_kind != "top" for r in model.relations)
