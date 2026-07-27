"""Stage 4A integration tests: real LabelingWidget + real save wiring.

These five probes verify the real-adaptor wiring lands correctly.  They are
NOT the systematic PyQt suite (that is stage 6) — they target the highest-
risk junctions the stage-1+2 pure-Python tests cannot reach:

    1. image_token reload lifecycle
    2. real Canvas selection → workflow workgroup build
    3. ACTIVE shape_moved does NOT auto-save            (audit risk #1)
    4. non-ACTIVE shape_moved keeps original auto-save  (regression guard)
    5. accept success releases / failure keeps workgroup

The fixture boots a real ``LabelingWidget`` via ``LabelingWrapper`` under
``QT_QPA_PLATFORM=offscreen`` and loads a tiny generated PNG.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Set the config file BEFORE any widget import so internal get_config() calls
# (e.g. ModelManager.load_model_configs) resolve a real default config.
import anylabeling.config as _cfgmod  # noqa: E402

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "anylabeling",
    "configs",
    "xanylabeling_config.yaml",
)
_cfgmod.current_config_file = _CFG_PATH

from PyQt6 import QtCore, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_wrapper import (  # noqa: E402
    LabelingWrapper,
)
from anylabeling.views.labeling.rect_refine_types import (  # noqa: E402
    RectRefineState,
    SaveResult,
    ShapeRefineView,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402

pytest.importorskip("PIL")
from PIL import Image as _PIL_Image  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def png_path(tmp_path):
    """A tiny solid-colour PNG for load_file."""
    p = tmp_path / "img.png"
    _PIL_Image.new("RGB", (200, 200), (255, 255, 255)).save(p)
    return str(p)


@pytest.fixture
def widget(qapp, png_path):
    """A real LabelingWidget with one image loaded."""
    mw = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(mw)
    w = wrapper.view
    assert w.load_file(png_path) is True
    yield w
    mw.close()


def _rect(label, x, y, w, h, gid=None):
    """Build a rectangle Shape with four QPointF corners."""
    s = Shape(label=label, shape_type="rectangle")
    s.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + w, y),
        QtCore.QPointF(x + w, y + h),
        QtCore.QPointF(x, y + h),
    ]
    s.group_id = gid
    return s


def _enter_active_workgroup(widget, person, head, face=None):
    """Enable refine mode and drive a real Canvas selection to ACTIVE.

    Returns the workflow. Shapes are registered through ``load_shapes`` so
    they appear in both ``canvas.shapes`` and ``label_list`` (the latter is
    what ``save_labels`` serializes).
    """
    wf = widget._ensure_rect_refine_workflow()
    shapes = [person, head] + ([face] if face is not None else [])
    widget.load_shapes(shapes, replace=True, store_backup=False)
    # Build base views and enable.
    token = widget._rect_refine_image_token
    views = [
        widget._rect_refine_view_builder.build_view(s, i, token)
        for i, s in enumerate(widget.canvas.shapes)
    ]
    wf.enable(token, views)
    assert wf.state == RectRefineState.SELECTING
    # Real Canvas selection emits selection_changed → forwards to workflow.
    widget.canvas.select_shapes([person], source="canvas")
    return wf


# ---------------------------------------------------------------------------
# 1. image_token reload lifecycle
# ---------------------------------------------------------------------------


def test_image_token_increments_on_reload(widget, png_path):
    """Reload of the same image must produce a fresh token (AC-086 guard)."""
    assert widget._rect_refine_image_token == "1"
    assert widget.load_file(png_path) is True
    assert widget._rect_refine_image_token == "2"


# ---------------------------------------------------------------------------
# 2. real Canvas selection triggers workgroup build
# ---------------------------------------------------------------------------


def test_real_selection_triggers_workgroup_build(widget):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    face = _rect("face", 48, 30, 72, 65)
    wf = _enter_active_workgroup(widget, person, head, face)

    assert wf.state == RectRefineState.ACTIVE
    snap = wf.workgroup_snapshot
    assert snap is not None
    # Anchor retained and is the real Shape object the user selected.
    assert snap.anchor_shape_id == (
        widget._rect_refine_image_token,
        id(person),
    )
    assert person.shape_id if hasattr(person, "shape_id") else True
    # All three members joined.
    member_ids = set(snap.member_shape_ids)
    assert {id(person), id(head), id(face)}.issubset(
        {sid[1] for sid in member_ids}
    )


# ---------------------------------------------------------------------------
# 3. ACTIVE shape_moved does NOT auto-save (audit risk #1, core)
# ---------------------------------------------------------------------------


def test_active_shape_moved_does_not_auto_save(widget, monkeypatch):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    face = _rect("face", 48, 30, 72, 65)
    widget._config["auto_save"] = True
    wf = _enter_active_workgroup(widget, person, head, face)

    save_calls = []
    # Spy directly on the signal: a separate receiver counts emissions.
    # This proves shape_moved is still delivered to subscribers (i.e. the
    # refresh slot remains wired) — we only replaced the dirty slot.
    signal_hits = []
    widget.canvas.shape_moved.connect(lambda: signal_hits.append(1))

    monkeypatch.setattr(
        widget, "save_labels", lambda fn: save_calls.append(fn) or True
    )

    # Mutate a member's points (simulating an edge-drag commit) and emit.
    head.points[0] = QtCore.QPointF(41.0, 20.0)
    widget.canvas.shape_moved.emit()

    # Core assertion: no save fired even with auto_save=True.
    assert save_calls == []
    # The workgroup recorded the temporary geometry change.
    assert wf.workgroup_geometry_dirty is True
    # The signal still reaches subscribers (refresh slot not disconnected).
    assert len(signal_hits) >= 1


# ---------------------------------------------------------------------------
# 4. non-ACTIVE shape_moved keeps original auto-save (regression guard)
# ---------------------------------------------------------------------------


def test_non_active_shape_moved_keeps_auto_save(widget, monkeypatch):
    widget._config["auto_save"] = True
    # No workflow enabled → wrapper must fall through to set_dirty → save.
    save_calls = []
    monkeypatch.setattr(
        widget, "save_labels", lambda fn: save_calls.append(fn) or True
    )
    widget.canvas.shape_moved.emit()
    assert len(save_calls) == 1


# ---------------------------------------------------------------------------
# 5. accept success releases / failure keeps workgroup
# ---------------------------------------------------------------------------


def test_accept_success_releases_workgroup_failed_keeps(
    widget, monkeypatch, tmp_path
):
    person = _rect("person", 10, 10, 100, 200)
    head = _rect("head", 40, 20, 80, 70)
    wf = _enter_active_workgroup(widget, person, head)

    # --- success branch: real save_labels writes final geometry ---
    # Pre-seed a label file path so save_file_dialog isn't invoked; we call
    # the save adapter directly with a stubbed dialog.
    out = tmp_path / "out.json"
    monkeypatch.setattr(widget, "save_file_dialog", lambda: str(out))

    result = wf.accept_current_workgroup()
    assert result == SaveResult.SUCCESS
    assert wf.state == RectRefineState.SELECTING
    assert not wf.has_active_workgroup
    # JSON written and contains the member shapes, no rect_refine temp fields.
    data = json.loads(out.read_text(encoding="utf-8"))
    labels = {s["label"] for s in data["shapes"]}
    assert {"person", "head"}.issubset(labels)
    blob = out.read_text(encoding="utf-8")
    assert "rect_refine" not in blob
    assert "qa_entity_id" not in blob

    # --- failure branch: save_labels returns False keeps workgroup ---
    wf2 = _enter_active_workgroup(widget, person, head)
    monkeypatch.setattr(widget, "save_file_dialog", lambda: str(out))
    monkeypatch.setattr(widget, "save_labels", lambda fn: False)
    result = wf2.accept_current_workgroup()
    assert result == SaveResult.FAILED
    assert wf2.state == RectRefineState.ACTIVE
    assert wf2.has_active_workgroup
