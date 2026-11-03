"""Live rectangle size readout and per-label minimum-size rules."""

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.rectangle_size import (
    RectangleCandidate,
    RectangleSizeConfigError,
    RectangleSizeEvaluator,
    RectangleSizeRule,
    layout_overlay_items,
    load_rectangle_size_rules,
    parse_rectangle_size_rules,
    serialize_rectangle_size_rules,
)
from anylabeling.views.labeling.rectangle_size.layout import (
    OverlayLayoutItem,
)
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.widgets.rectangle_edge import EdgeDrag


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication):
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(320, 240)
    widget.pixmap.fill(QtGui.QColor("white"))
    widget.resize(320, 240)
    widget.load_shapes(
        [
            make_rectangle("cat", 20, 20, 90, 80),
            make_rectangle("cat", 120, 100, 150, 120),
        ]
    )
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def make_rectangle(label, left, top, right, bottom):
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    return shape


def make_candidate(label, bbox, index=0, shape_type="rectangle"):
    return RectangleCandidate(
        candidate_id=index,
        shape_index=index,
        label=label,
        shape_type=shape_type,
        bbox=bbox,
    )


def render(canvas):
    image = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("black"))
    canvas.render(image)
    return image


# --- Pure evaluator ---------------------------------------------------


def test_value_equal_to_threshold_is_abnormal():
    evaluator = RectangleSizeEvaluator([RectangleSizeRule("cat", 30, 30)])
    issue = evaluator.evaluate_candidate(make_candidate("cat", (0, 0, 30, 40)))
    assert issue is not None
    assert [v.dimension for v in issue.violations] == ["width"]


def test_any_mode_triggers_on_one_failed_dimension():
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule("cat", 30, 30, "any")]
    )
    assert evaluator.evaluate_candidate(make_candidate("cat", (0, 0, 10, 90)))


def test_all_mode_requires_every_dimension_to_fail():
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule("cat", 30, 30, "all")]
    )
    assert (
        evaluator.evaluate_candidate(make_candidate("cat", (0, 0, 10, 90)))
        is None
    )
    assert evaluator.evaluate_candidate(make_candidate("cat", (0, 0, 10, 10)))


def test_disabled_rule_is_ignored():
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule("cat", 30, 30, enabled=False)]
    )
    assert evaluator.evaluate_candidate(make_candidate("cat", (0, 0, 1, 1))) is None


def test_unmatched_label_and_non_rectangles_are_skipped():
    evaluator = RectangleSizeEvaluator([RectangleSizeRule("cat", 30, 30)])
    assert evaluator.evaluate_candidate(make_candidate("dog", (0, 0, 1, 1))) is None
    assert (
        evaluator.evaluate_candidate(
            make_candidate("cat", (0, 0, 1, 1), shape_type="polygon")
        )
        is None
    )


def test_inactive_candidate_is_skipped():
    evaluator = RectangleSizeEvaluator([RectangleSizeRule("cat", 30, 30)])
    candidate = RectangleCandidate(0, 0, "cat", "rectangle", (0, 0, 1, 1), False)
    assert evaluator.evaluate_candidate(candidate) is None


@pytest.mark.parametrize(
    "rule",
    [
        RectangleSizeRule("cat"),
        RectangleSizeRule("  ", 10, 10),
        RectangleSizeRule("cat", 0, 10),
        RectangleSizeRule("cat", float("nan"), 10),
        RectangleSizeRule("cat", 10, 10, "sometimes"),
    ],
)
def test_invalid_enabled_rules_are_rejected(rule):
    with pytest.raises(ValueError):
        RectangleSizeEvaluator([rule])


def test_duplicate_enabled_rule_is_rejected():
    with pytest.raises(ValueError):
        RectangleSizeEvaluator(
            [RectangleSizeRule("cat", 10, 10), RectangleSizeRule("cat", 20, 20)]
        )


# --- Configuration codec ---------------------------------------------


def test_config_round_trip_keeps_every_field():
    rules = (
        RectangleSizeRule("cat", 24, None, "any", True),
        RectangleSizeRule("dog", 12, 18, "all", False),
    )
    rows = serialize_rectangle_size_rules(rules)
    assert parse_rectangle_size_rules(rows) == rules


def test_config_rejects_unknown_field():
    with pytest.raises(RectangleSizeConfigError) as excinfo:
        parse_rectangle_size_rules([{"label": "cat", "min_width_px": 4, "x": 1}])
    assert excinfo.value.code == "unexpected_fields"


def test_config_rejects_duplicate_label():
    with pytest.raises(RectangleSizeConfigError) as excinfo:
        parse_rectangle_size_rules(
            [
                {"label": "cat", "min_width_px": 4},
                {"label": "cat", "min_height_px": 4},
            ]
        )
    assert excinfo.value.code == "duplicate_label"


def test_config_rejects_enabled_rule_without_threshold():
    with pytest.raises(RectangleSizeConfigError) as excinfo:
        parse_rectangle_size_rules([{"label": "cat", "enabled": True}])
    assert excinfo.value.code == "missing_threshold"


def test_config_allows_disabled_rule_without_threshold():
    rules = parse_rectangle_size_rules(
        [{"label": "cat", "enabled": False, "min_width_px": ""}]
    )
    assert rules[0].enabled is False
    assert rules[0].min_width_px is None


def test_missing_config_key_means_no_rules():
    assert load_rectangle_size_rules({}) == ()
    assert load_rectangle_size_rules({"rectangle_size_rules": None}) == ()


# --- Overlay layout ---------------------------------------------------


def test_layout_keeps_every_overlay_in_order():
    items = [
        OverlayLayoutItem(
            candidate_id=index,
            bbox=(20.0, 20.0, 40.0, 40.0),
            box_width=120.0,
            box_height=18.0,
        )
        for index in range(12)
    ]
    placements = layout_overlay_items(items, (0.0, 0.0, 320.0, 240.0))
    assert len(placements) == len(items)
    assert [p.candidate_id for p in placements] == list(range(len(items)))


def test_layout_separates_overlays_of_adjacent_boxes():
    items = [
        OverlayLayoutItem(0, (10.0, 10.0, 30.0, 30.0), 100.0, 18.0),
        OverlayLayoutItem(1, (12.0, 12.0, 32.0, 32.0), 100.0, 18.0),
    ]
    placements = layout_overlay_items(items, (0.0, 0.0, 320.0, 240.0))
    first, second = (p.rect for p in placements)
    overlap_x = min(first[0] + first[2], second[0] + second[2]) - max(
        first[0], second[0]
    )
    overlap_y = min(first[1] + first[3], second[1] + second[3]) - max(
        first[1], second[1]
    )
    assert overlap_x <= 0 or overlap_y <= 0


def test_layout_clamps_overlay_into_viewport():
    items = [
        OverlayLayoutItem(0, (300.0, 230.0, 320.0, 240.0), 120.0, 18.0)
    ]
    placement = layout_overlay_items(items, (0.0, 0.0, 320.0, 240.0))[0]
    x, y, width, height = placement.rect
    assert 0.0 <= x and x + width <= 320.0
    assert 0.0 <= y and y + height <= 240.0


# --- Canvas readout ---------------------------------------------------


def test_readout_is_off_by_default(canvas):
    first, _ = canvas.shapes
    canvas.selected_shapes = [first]
    assert canvas._normal_size_overlay_request() is None


def test_readout_reports_selected_rectangle(canvas):
    first, _ = canvas.shapes
    first.selected = True
    canvas.selected_shapes = [first]
    canvas.show_rectangle_pixels = True

    request = canvas._normal_size_overlay_request()

    assert request is not None
    assert request.lines == ("W 70.0 px  H 60.0 px",)
    assert request.bbox == (20.0, 20.0, 90.0, 80.0)
    assert request.warning is False


def test_readout_prefers_edge_drag_over_hover(canvas):
    first, second = canvas.shapes
    canvas.show_rectangle_pixels = True
    canvas.h_shape = second
    canvas._rectangle_edge_drag = EdgeDrag(
        shape=first,
        edge="left",
        press=QtCore.QPointF(20.0, 20.0),
        points=list(first.points),
    )

    assert canvas._normal_size_overlay_request().bbox == (20.0, 20.0, 90.0, 80.0)


def test_readout_prefers_hover_over_selection(canvas):
    first, second = canvas.shapes
    first.selected = True
    canvas.selected_shapes = [first]
    canvas.h_shape = second
    canvas.show_rectangle_pixels = True

    assert canvas._normal_size_overlay_request().bbox == (120.0, 100.0, 150.0, 120.0)


def test_readout_tracks_in_progress_creation(canvas):
    canvas.show_rectangle_pixels = True
    canvas.mode = Canvas.CREATE
    canvas.create_mode = "rectangle"
    canvas.current = [QtCore.QPointF(10.0, 20.0)]
    canvas.line.points = [QtCore.QPointF(0.0, 0.0), QtCore.QPointF(30.0, 50.0)]

    request = canvas._normal_size_overlay_request()

    assert request is not None
    assert request.bbox == (10.0, 20.0, 30.0, 50.0)
    assert request.lines == ("W 20.0 px  H 30.0 px",)


def test_readout_skips_shapes_hidden_in_object_panel(canvas):
    first, _ = canvas.shapes
    first.selected = True
    first.visible = False
    canvas.selected_shapes = [first]
    canvas.show_rectangle_pixels = True

    assert canvas._normal_size_overlay_request() is None


def test_readout_skips_shapes_hidden_by_layer_visibility(canvas):
    first, _ = canvas.shapes
    first.selected = True
    canvas.selected_shapes = [first]
    canvas.visible[first] = False
    canvas.show_rectangle_pixels = True

    assert canvas._normal_size_overlay_request() is None


def test_readout_skips_unselected_shapes_in_focus_mode(canvas):
    first, second = canvas.shapes
    canvas.selected_shapes = [first]
    canvas.h_shape = second
    canvas.show_rectangle_pixels = True
    canvas._hide_backround = True

    assert canvas._normal_size_overlay_request() is None


def test_readout_anchors_to_the_painted_label_box(canvas):
    first, _ = canvas.shapes
    first.selected = True
    canvas.selected_shapes = [first]
    canvas.show_rectangle_pixels = True

    label_rect = canvas._size_overlay_label_rect(first)

    assert label_rect is not None
    x, y, width, height = label_rect
    assert width > 0 and height > 0
    assert y + height <= 20.0
    assert x <= 20.0


# --- Rule warnings ----------------------------------------------------


def test_rules_schedule_a_rescan_when_cache_is_stale(canvas):
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True

    assert canvas._rectangle_size_scan_timer.isActive()


def test_violations_are_reported_for_small_rectangles(canvas):
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True

    canvas._rescan_rectangle_size_issues()

    issues = canvas.rectangle_size_issues
    assert [issue.shape_index for issue in issues] == [1]
    assert issues[0].width == 30.0
    assert issues[0].height == 20.0


def test_violations_respect_equality_boundary(canvas):
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 30, 30)])
    canvas.show_rectangle_size_violations = True

    canvas._rescan_rectangle_size_issues()

    assert [issue.shape_index for issue in canvas.rectangle_size_issues] == [1]


def test_violations_skip_shapes_hidden_in_object_panel(canvas):
    first, second = canvas.shapes
    second.visible = False
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True

    canvas._rescan_rectangle_size_issues()

    assert canvas.rectangle_size_issues == ()


def test_unhiding_shape_schedules_size_warning_rescan(canvas: Canvas) -> None:
    """An object omitted from the cached scan is checked when shown."""
    second = canvas.shapes[1]
    second.visible = False
    canvas.set_shape_visible(second, False)
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True
    canvas._rectangle_size_scan_timer.stop()
    canvas._rescan_rectangle_size_issues()
    assert not canvas.rectangle_size_issues

    second.visible = True
    canvas.set_shape_visible(second, True)

    assert canvas._rectangle_size_scan_timer.isActive()
    canvas._rectangle_size_scan_timer.stop()
    canvas._rescan_rectangle_size_issues()
    assert len(canvas.rectangle_size_issues) == 1


def test_leaving_focus_mode_schedules_size_warning_rescan(
    canvas: Canvas,
) -> None:
    """Restoring background objects also restores their rule warnings."""
    canvas.hide_backround = True
    canvas.shapes[0].selected = True
    canvas.set_hiding(True)
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True
    canvas._rectangle_size_scan_timer.stop()
    canvas._rescan_rectangle_size_issues()
    assert not canvas.rectangle_size_issues

    canvas.set_hiding(False)

    assert canvas._rectangle_size_scan_timer.isActive()
    canvas._rectangle_size_scan_timer.stop()
    canvas._rescan_rectangle_size_issues()
    assert len(canvas.rectangle_size_issues) == 1


def test_disabling_violations_clears_cached_issues(canvas):
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True
    canvas._rescan_rectangle_size_issues()
    assert canvas.rectangle_size_issues

    canvas.show_rectangle_size_violations = False

    assert canvas.rectangle_size_issues == ()
    assert not canvas._rectangle_size_scan_timer.isActive()


def test_warning_request_replaces_plain_readout_for_the_same_shape(canvas):
    second = canvas.shapes[1]
    second.selected = True
    canvas.selected_shapes = [second]
    canvas.show_rectangle_pixels = True
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True
    canvas._rescan_rectangle_size_issues()

    requests = canvas._normal_size_overlay_request(), (
        canvas._violation_overlay_requests()
    )
    from anylabeling.views.labeling.widgets.rectangle_size_overlay import (
        merge_overlay_requests,
    )

    merged = merge_overlay_requests(requests[0], requests[1])

    assert len(merged) == 1
    assert merged[0].warning is True


def test_warning_paint_marks_the_violating_rectangle(canvas):
    canvas.show_rectangle_pixels = True
    plain = render(canvas)
    canvas.set_rectangle_size_rules([RectangleSizeRule("cat", 40, 40)])
    canvas.show_rectangle_size_violations = True
    canvas._rescan_rectangle_size_issues()

    warned = render(canvas)

    assert plain != warned


# --- Action wiring ----------------------------------------------------


def test_action_switch_updates_canvas_and_config():
    from types import SimpleNamespace
    from unittest.mock import Mock

    host = SimpleNamespace(
        _config={},
        canvas=SimpleNamespace(
            show_rectangle_pixels=False, update=Mock()
        ),
    )

    LabelingWidget.set_canvas_params(host, "show_rectangle_pixels", True)

    assert host.canvas.show_rectangle_pixels is True
    assert host._config["show_rectangle_pixels"] is True
    host.canvas.update.assert_called_once()
