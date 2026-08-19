"""Offscreen integration checks for virtual-review page lifecycle."""

import copy
from types import SimpleNamespace

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.widgets.inspector.virtual_review_controller import (
    VirtualReviewController,
)
from anylabeling.views.labeling.widgets.inspector.virtual_review_widget import (
    VirtualReviewWidget,
)


class _Canvas:
    """Small canvas double that exposes the controller boundary contract."""

    def __init__(self, shapes):
        self.shapes = shapes
        self.predicate = None
        self.drawing_state = False
        self.rect_edge_dragging = False
        self.moving_shape = False
        self.scale = 1.0
        self.pixmap = None
        self.deselect_calls = 0
        self.adjust_size_calls = 0

    def drawing(self):
        return self.drawing_state

    def base_visible(self, shape):
        return bool(shape.visible)

    def set_virtual_review_visibility_predicate(self, predicate):
        self.predicate = predicate

    def clear_virtual_review_visibility_predicate(self):
        self.predicate = None

    def deselect_shape(self):
        self.deselect_calls += 1
        return None

    def select_shapes(self, shapes):
        for shape in shapes:
            shape.selected = True

    def adjustSize(self):
        self.adjust_size_calls += 1

    def size(self):
        return QtCore.QSize(1200, 800)


class _Shape:
    """Small mutable shape double used without production import ordering."""

    def __init__(self, label, x, group_id=None):
        """Initialize the controller-facing shape attributes."""
        self.label = label
        self.x = x
        self.shape_type = "rectangle"
        self.group_id = group_id
        self.visible = True
        self.selected = False

    def bounding_rect(self):
        """Return a stable 20-pixel rectangle."""
        return QtCore.QRectF(self.x, 10, 20, 20)


def _shape(label, x, group_id=None):
    return _Shape(label, x, group_id)


def _payload(labels="person", **packing):
    return {
        "criteria": {
            "labels": frozenset({labels}),
            "shape_types": frozenset({"rectangle"}),
        },
        "packing": packing,
    }


def _controller(qapp, shapes=None):
    host = QtWidgets.QWidget()
    host.canvas = _Canvas(shapes if shapes is not None else [])
    host.status_messages = []
    host.status = host.status_messages.append
    host.zoom_calls = []
    host.fit_window_calls = []
    host.set_zoom = lambda value: host.zoom_calls.append(value)
    host.set_fit_window = lambda: host.fit_window_calls.append(1)
    scroll = QtWidgets.QScrollArea()
    scroll.resize(1200, 800)
    host._central_widget = scroll
    host.zoom_widget = SimpleNamespace(value=lambda: 100)
    host.zoom_mode = 0
    host.viewport_controller = SimpleNamespace(
        capture_result=lambda *args: SimpleNamespace(
            success=False, state=None
        ),
        apply_result=lambda *args: SimpleNamespace(success=True),
    )
    review = VirtualReviewWidget()
    controller = VirtualReviewController(host, review)
    return host, review, controller


def test_navigation_moves_between_pages_without_overview_intermediate(qapp):
    shapes = [_shape("person", 10), _shape("person", 1000)]
    host, review, controller = _controller(qapp, shapes)

    controller.start(_payload())
    assert controller.active
    assert controller._session.index == 0
    assert controller._overview is False

    controller.next()

    assert controller._session.index == 1
    assert controller._overview is False
    assert host.canvas.predicate is not None
    assert not host.fit_window_calls
    restored = []
    host._sync_viewport_ui = restored.append
    state = SimpleNamespace(zoom_value=100)
    controller._captured_viewport = state
    controller.stop()
    assert restored == [state]
    review.deleteLater()
    host.deleteLater()


def test_multi_task_page_installs_union_membership(qapp):
    shapes = [_shape("person", 10), _shape("person", 400)]
    host, review, controller = _controller(qapp, shapes)

    controller.start(
        _payload(
            max_tasks_per_page=2,
            min_projected_anchor_px=10,
            min_projected_gap_px=5,
        )
    )

    result = controller._packing_result
    assert result.page_count == 1
    assert result.atomic_task_count == 2
    page = controller._session.current
    assert page.task_count == 2

    predicate = host.canvas.predicate
    assert predicate(shapes[0]) and predicate(shapes[1])
    non_page = _shape("person", 2000)
    assert not predicate(non_page)
    assert shapes[0].selected is True
    assert not getattr(shapes[1], "selected", False)
    assert host.zoom_calls
    review.deleteLater()
    host.deleteLater()


def test_invalid_packing_input_keeps_active_session(qapp):
    shapes = [_shape("person", 10), _shape("person", 1000)]
    host, review, controller = _controller(qapp, shapes)
    controller.start(_payload())
    assert controller.active
    before_pages = controller._session.pages
    before_index = controller._session.index

    controller.start(_payload(max_tasks_per_page=9))

    assert controller.active
    assert controller._session.pages == before_pages
    assert controller._session.index == before_index
    assert any("条件无效" in message for message in host.status_messages)
    review.deleteLater()
    host.deleteLater()


def test_partial_deletion_retains_surviving_members(qapp):
    shapes = [_shape("person", 10), _shape("person", 400)]
    host, review, controller = _controller(qapp, shapes)
    controller.start(
        _payload(
            max_tasks_per_page=2,
            min_projected_anchor_px=10,
            min_projected_gap_px=5,
        )
    )
    page = controller._session.current
    assert page.task_count == 2

    del host.canvas.shapes[1]
    controller._activate_current()

    assert controller._session.current is page
    predicate = host.canvas.predicate
    assert predicate(shapes[0])
    text = review.progress_label.text()
    assert "1" in text
    review.deleteLater()
    host.deleteLater()


def test_duplicate_shape_receives_new_runtime_identity(qapp):
    original = _shape("person", 10)
    host, review, controller = _controller(qapp, [original])
    controller.start(_payload())
    original_id = original._virtual_review_id

    duplicate = copy.deepcopy(original)
    duplicate.x = 100
    host.canvas.shapes.append(duplicate)
    controller._activate_current()

    assert duplicate._virtual_review_id != original_id
    assert host.canvas.predicate(original)
    assert not host.canvas.predicate(duplicate)
    review.deleteLater()
    host.deleteLater()


def test_fully_deleted_page_is_skipped(qapp):
    shapes = [_shape("person", 10), _shape("person", 1000)]
    host, review, controller = _controller(qapp, shapes)
    controller.start(_payload())
    assert controller._session.index == 0

    del host.canvas.shapes[0]
    controller.next()

    assert controller._session.index == 1
    assert host.canvas.predicate is not None
    assert any("跳过" in message for message in host.status_messages)
    review.deleteLater()
    host.deleteLater()


def test_image_load_rebuilds_pages(qapp):
    shapes = [_shape("person", 10), _shape("person", 1000)]
    host, review, controller = _controller(qapp, shapes)
    controller.start(_payload())
    assert controller._packing_result.page_count == 2

    host.canvas.shapes = [_shape("person", 10)]
    controller.on_image_loaded()

    assert controller.active
    assert controller._packing_result.page_count == 1
    assert len(controller._session.pages) == 1
    review.deleteLater()
    host.deleteLater()


def test_overview_keeps_predicate_and_returns_to_page(qapp):
    shapes = [_shape("person", 10)]
    host, review, controller = _controller(qapp, shapes)
    controller.start(_payload())

    controller.toggle_overview()

    assert controller._overview is True
    assert host.fit_window_calls == [1]
    assert host.canvas.predicate is not None

    controller.toggle_overview()

    assert controller._overview is False
    assert host.canvas.predicate is not None
    assert host.zoom_calls
    review.deleteLater()
    host.deleteLater()
