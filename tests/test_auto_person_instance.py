"""Tests for Feature 1: auto_person_instance (task 7.1-7.3, 7.16).

Validates that drawing a ``person`` rectangle auto-mints a fresh
``group_id`` when ``auto_person_instance`` is enabled, with the documented
priority (bind_draw pending > auto_person_instance > auto_use_last_gid)
and the Non-Goal that auto-labeling landing does not trigger it.

These tests exercise the ``new_shape`` group_id-resolution block in
isolation via ``LabelingWidget.new_shape`` called on a lightweight
stand-in (mirrors the pattern in ``test_feature_interactions.py``).
"""

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import MockShape


def _make_widget(canvas, config, last_label="", last_gid=None):
    """Build a minimal LabelingWidget stand-in for new_shape tests.

    ``new_shape`` reads: ``self.canvas.shapes[-1]``, ``self._config``,
    ``self.find_last_label()``, ``self.find_last_gid()``,
    ``self.validate_label``, ``self.status``, ``self.tr``,
    ``self.unique_label_list.selectedItems()``, ``self.label_dialog``.
    We short-circuit the popup path by pre-setting ``self.digit_to_label``
    and leaving ``display_label_popup`` False so the dialog is never
    consulted.
    """
    from anylabeling.views.labeling.label_widget import LabelingWidget

    w = types.SimpleNamespace()
    w.canvas = canvas
    w._config = config
    w.digit_to_label = None
    w.find_last_label = lambda: last_label
    w.find_last_gid = lambda: last_gid
    w.validate_label = lambda text: True
    w.status = lambda *a, **k: None
    w.tr = lambda x: x
    # Bind the extracted helpers so new_shape can delegate to them via
    # the stand-in self.
    w._apply_auto_person_instance = (
        lambda text: LabelingWidget._apply_auto_person_instance(w, text)
    )
    w._consume_digit_bind = (
        lambda last_gid: LabelingWidget._consume_digit_bind(w, last_gid)
    )
    # unique_label_list with no selection -> text stays None, then the
    # auto_use_last_label / digit branches decide text.
    w.unique_label_list = types.SimpleNamespace(selectedItems=lambda: [])
    w.attributes = None
    w.set_dirty = lambda: None
    # Stub trailing new_shape UI side effects.
    _action_stub = types.SimpleNamespace(setEnabled=lambda x: None)
    w.actions = types.SimpleNamespace(
        edit_mode=_action_stub,
        undo_last_point=_action_stub,
        undo=_action_stub,
        create_brush_polygon_mode=types.SimpleNamespace(
            isEnabled=lambda: False
        ),
    )
    w.show_attributes_panel = lambda: None
    w.update_attributes = lambda i: None
    return w


def _base_config(**overrides):
    cfg = {
        "display_label_popup": False,
        "auto_use_last_label": False,
        "auto_use_last_gid": False,
        "auto_person_instance": False,
        "validate_label": None,
    }
    cfg.update(overrides)
    return cfg


def _new_rect(label="person"):
    """A freshly drawn person rectangle (group_id=None)."""
    return MockShape(label=label, shape_type="rectangle")


def test_7_1_auto_person_instance_mints_new_group_id(canvas):
    """7.1: with auto_person_instance ON, a new person rectangle gets a
    fresh group_id = max(existing)+1."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    # Two existing shapes (gid 1, 3) plus the just-drawn new rectangle
    # (gid None) at shapes[-1]. Next group_id must be max(1,3)+1 = 4.
    canvas.shapes = [
        MockShape(label="person", shape_type="rectangle", group_id=1),
        MockShape(label="person", shape_type="rectangle", group_id=3),
        MockShape(label="person", shape_type="rectangle"),
    ]
    canvas.gen_new_group_id = (
        lambda: max(
            (s.group_id for s in canvas.shapes if s.group_id is not None),
            default=0,
        )
        + 1
    )

    captured_group_id = {}

    def fake_set_last_label(text, flags, group_id):
        captured_group_id["gid"] = group_id
        # Return the last shape, mirroring Canvas.set_last_label.
        return canvas.shapes[-1]

    canvas.set_last_label = fake_set_last_label

    cfg = _base_config(auto_person_instance=True, auto_use_last_label=True)
    cfg["auto_use_last_label"] = True
    w = _make_widget(canvas, cfg, last_label="person")
    # Stub the trailing new_shape side effects we don't exercise here.
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    assert (
        captured_group_id["gid"] == 4
    ), "auto_person_instance must mint max(existing)+1 = 4"


def test_7_2_auto_person_instance_with_auto_use_last_label_consecutive(
    canvas,
):
    """7.2: NOT mutually exclusive with auto_use_last_label. With both ON
    and last_label == 'person', each new person gets a fresh group_id
    (not the previous one)."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    canvas.shapes = [_new_rect()]
    canvas.gen_new_group_id = (
        lambda: max(
            (s.group_id for s in canvas.shapes if s.group_id is not None),
            default=0,
        )
        + 1
    )

    captured = {}

    def fake_set_last_label(text, flags, group_id):
        captured["text"] = text
        captured["gid"] = group_id
        return canvas.shapes[-1]

    canvas.set_last_label = fake_set_last_label

    cfg = _base_config(auto_person_instance=True, auto_use_last_label=True)
    w = _make_widget(canvas, cfg, last_label="person")
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    # Label is reused from last_label (auto_use_last_label), but group_id
    # is a fresh 1 (no existing gids), NOT None and NOT inherited.
    assert captured["text"] == "person"
    assert (
        captured["gid"] == 1
    ), "consecutive person must get fresh gid 1, not last gid"


def test_7_3_auto_person_instance_priority_over_auto_use_last_gid(canvas):
    """7.3: when both auto_person_instance and auto_use_last_gid are ON,
    the person rectangle gets a FRESH group_id (priority), not last_gid."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    # Existing shapes with gid 2 -> last_gid would be 2, but fresh = 3.
    existing = MockShape(label="person", shape_type="rectangle", group_id=2)
    canvas.shapes = [existing, _new_rect()]
    canvas.gen_new_group_id = (
        lambda: max(
            (s.group_id for s in canvas.shapes if s.group_id is not None),
            default=0,
        )
        + 1
    )

    captured = {}

    def fake_set_last_label(text, flags, group_id):
        captured["gid"] = group_id
        return canvas.shapes[-1]

    canvas.set_last_label = fake_set_last_label

    cfg = _base_config(
        auto_person_instance=True,
        auto_use_last_gid=True,
        auto_use_last_label=True,
    )
    w = _make_widget(canvas, cfg, last_label="person", last_gid=2)
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    assert (
        captured["gid"] == 3
    ), "auto_person_instance must win: fresh 3, not last_gid 2"


def test_bind_draw_group_id_wins_over_auto_person_instance(canvas):
    """Regression: bind_draw gid must not be overwritten by feature 1."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    source = MockShape(label="head", shape_type="rectangle", group_id=7)
    new_person = _new_rect(label="person")
    canvas.shapes = [source, new_person]
    canvas.gen_new_group_id = lambda: 99

    captured = {}

    def fake_set_last_label(text, flags, group_id):
        captured["text"] = text
        captured["gid"] = group_id
        return canvas.shapes[-1]

    class FakeBindManager:
        def __init__(self):
            self.cleared = False

        def consume_pending(self):
            return ("person", 7, source, False)

        def clear_pending(self):
            self.cleared = True

    bind_manager = FakeBindManager()
    canvas.set_last_label = fake_set_last_label
    cfg = _base_config(
        auto_person_instance=True,
        auto_use_last_gid=True,
        auto_use_last_label=True,
    )
    w = _make_widget(canvas, cfg, last_label="person", last_gid=3)
    w.digit_to_label = "person"
    w.digit_bind_draw_manager = bind_manager
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    assert captured == {"text": "person", "gid": 7}
    assert bind_manager.cleared is True


def test_7_1b_auto_person_instance_off_keeps_group_id_none(canvas):
    """Sanity: with the flag OFF, a person rectangle keeps group_id=None
    (existing default behavior unchanged)."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    canvas.shapes = [_new_rect()]
    canvas.gen_new_group_id = lambda: 1

    captured = {}

    def fake_set_last_label(text, flags, group_id):
        captured["gid"] = group_id
        return canvas.shapes[-1]

    canvas.set_last_label = fake_set_last_label

    cfg = _base_config(auto_person_instance=False, auto_use_last_label=True)
    w = _make_widget(canvas, cfg, last_label="person")
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    assert (
        captured["gid"] is None
    ), "feature OFF must keep legacy None group_id"


def test_7_1c_auto_person_instance_only_for_rectangle(canvas):
    """auto_person_instance must NOT fire for non-rectangle person shapes
    (e.g. polygon). Only rectangle is the instance anchor."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    polygon = MockShape(label="person", shape_type="polygon")
    canvas.shapes = [polygon]
    canvas.gen_new_group_id = lambda: 99  # should not be called

    captured = {}

    def fake_set_last_label(text, flags, group_id):
        captured["gid"] = group_id
        return canvas.shapes[-1]

    canvas.set_last_label = fake_set_last_label

    cfg = _base_config(auto_person_instance=True, auto_use_last_label=True)
    w = _make_widget(canvas, cfg, last_label="person")
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    assert (
        captured["gid"] is None
    ), "non-rectangle person must not auto-create instance"


def test_7_3b_auto_person_instance_does_not_fire_for_non_person(canvas):
    """Only label == 'person' triggers; 'head'/'face' must not mint."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    canvas.shapes = [_new_rect(label="head")]
    canvas.gen_new_group_id = lambda: 99  # should not be called

    captured = {}

    def fake_set_last_label(text, flags, group_id):
        captured["gid"] = group_id
        return canvas.shapes[-1]

    canvas.set_last_label = fake_set_last_label

    cfg = _base_config(auto_person_instance=True, auto_use_last_label=True)
    w = _make_widget(canvas, cfg, last_label="head")
    w.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    w.add_label = lambda shape: None

    LabelingWidget.new_shape(w)

    assert (
        captured["gid"] is None
    ), "non-person label must not trigger auto instance"


def test_consecutive_new_shapes_do_not_gain_visual_only_selection(canvas):
    """Creating shapes must not set ``selected`` outside selection state."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    first = _new_rect()
    canvas.shapes = [first]
    canvas.selected_shapes = []
    canvas.set_last_label = lambda text, flags, group_id: canvas.shapes[-1]

    widget = _make_widget(
        canvas,
        _base_config(auto_use_last_label=True),
        last_label="person",
    )
    widget.label_list = types.SimpleNamespace(clearSelection=lambda: None)
    widget.add_label = lambda shape: None
    shown = []
    updated = []
    widget.show_attributes_panel = lambda: shown.append(True)
    widget.update_attributes = updated.append

    LabelingWidget.new_shape(widget)

    second = _new_rect()
    canvas.shapes.append(second)
    LabelingWidget.new_shape(widget)

    assert canvas.selected_shapes == []
    assert first.selected is False
    assert second.selected is False
    assert shown == [True, True]
    assert updated == [0, 1]


def test_7_16_auto_labeling_path_does_not_use_auto_person_instance():
    """7.16 / Non-Goal: the auto-labeling landing path
    (finish_auto_labeling_object) must NOT read auto_person_instance.

    Static guard: the config key must not appear anywhere inside the
    finish_auto_labeling_object method body, only in new_shape.
    """
    import inspect

    from anylabeling.views.labeling.label_widget import LabelingWidget

    new_shape_src = inspect.getsource(LabelingWidget.new_shape)
    finish_src = inspect.getsource(LabelingWidget.finish_auto_labeling_object)

    assert (
        "auto_person_instance" in new_shape_src
    ), "auto_person_instance must be consulted in new_shape"
    assert (
        "auto_person_instance" not in finish_src
    ), "auto-labeling landing path must NOT trigger auto_person_instance"
