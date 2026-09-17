"""Qt integration coverage for density-round review visibility and sync."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.widgets.canvas import Canvas, Shape
from anylabeling.views.labeling.widgets.density_round_review import (
    DensityReviewCanvas,
    DensityRoundReviewCoordinator,
)
from anylabeling.views.labeling.widgets.selection.geometry import (
    shapes_intersecting_rect,
)


def _rectangle(
    label: str, left: float, top: float, right: float, bottom: float
) -> Shape:
    """Build one closed rectangle with a persistent identity."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    return shape


def _pixmap() -> QtGui.QPixmap:
    """Return a deterministic test image."""
    pixmap = QtGui.QPixmap(400, 200)
    pixmap.fill(QtGui.QColor("white"))
    return pixmap


class _Host(QtWidgets.QWidget):
    """Provide the narrow LabelingWidget contract used by the coordinator."""

    def __init__(self, settings_path: str) -> None:
        """Initialize an authoritative main Canvas and in-memory host state."""
        super().__init__()
        self.canvas = Canvas()
        self.canvas.resize(400, 200)
        self.canvas.load_pixmap(_pixmap())
        self.appearance_settings = self.canvas.appearance_settings
        self.appearance_label_colors = {}
        self._config = {
            "density_round_review": {"instances_per_round": 1},
            "shortcuts": {
                "density_review_previous": "[",
                "density_review_next": "]",
                "density_review_preview_all": "V",
            },
            "canvas": {
                "epsilon": 10.0,
                "double_click": "close",
                "num_backups": 10,
                "wheel_rectangle_editing": {},
                "attributes": {},
                "rotation": {},
                "mask": {},
                "brush": {},
                "cuboid": {},
                "double_click_edit_label": True,
            },
        }
        self.settings = QtCore.QSettings(
            settings_path, QtCore.QSettings.Format.IniFormat
        )
        self.filename = "0001.jpg"
        self.virtual_review_controller = SimpleNamespace(
            active=False, stop=lambda: None
        )
        self.label_list = SimpleNamespace(clear=lambda: None)
        self.dirty = False
        self.messages: list[str] = []
        self.density_round_review_controller = None

    def _update_shape_color(self, _shape: Shape) -> None:
        """Satisfy the host color-refresh contract."""

    def set_dirty(self) -> None:
        """Record that authoritative data changed."""
        self.dirty = True

    def load_shapes(
        self,
        shapes: list[Shape],
        replace: bool = True,
        update_last_label: bool = True,
        store_backup: bool = True,
    ) -> None:
        """Load authoritative shapes without a label-list implementation."""
        del update_last_label
        self.canvas.load_shapes(
            shapes, replace=replace, store_backup=store_backup
        )

    def undo_shape_edit(self) -> None:
        """Use the same coordinator hooks as LabelingWidget undo."""
        controller = self.density_round_review_controller
        restorable = self.canvas.is_shape_restorable
        controller.before_shared_undo()
        self.canvas.restore_shape()
        controller.after_shared_undo(restorable)

    def status(self, message: str, _timeout: int = 0) -> None:
        """Capture status text for assertions."""
        self.messages.append(message)

    def open_prev_image(self) -> None:
        """Keep the fake host at the dataset start."""

    def open_next_image(self) -> None:
        """Keep the fake host at the dataset end."""

    def may_continue(self) -> bool:
        """Allow navigation in tests that are not exercising save failure."""
        return True


@pytest.fixture
def review_host(
    qapp: QtWidgets.QApplication, tmp_path: Path
) -> Iterator[tuple[_Host, DensityRoundReviewCoordinator]]:
    """Create one enabled two-window review coordinator."""
    host = _Host(str(tmp_path / "density-review.ini"))
    host.load_shapes(
        [
            _rectangle("a", 20, 20, 70, 90),
            _rectangle("b", 250, 30, 320, 100),
        ]
    )
    controller = DensityRoundReviewCoordinator(host)
    host.density_round_review_controller = controller
    controller.enable()
    qapp.processEvents()
    yield host, controller
    controller.disable()
    if controller.window is not None:
        controller.window.close()
        controller.window.deleteLater()
    host.canvas.close()
    host.close()
    qapp.processEvents()


def test_canvas_inspection_gate_excludes_hidden_objects_everywhere(
    qapp: QtWidgets.QApplication,
) -> None:
    """Hidden round objects cannot be hit, hovered, or selected."""
    canvas = Canvas()
    canvas.resize(400, 200)
    canvas.load_pixmap(_pixmap())
    visible = _rectangle("visible", 20, 20, 70, 90)
    hidden = _rectangle("hidden", 250, 30, 320, 100)
    hidden.visible = False
    canvas.load_shapes([visible, hidden])
    canvas.set_inspection_visibility(
        render_predicate=lambda shape: shape is visible,
        interaction_predicate=lambda shape: shape is visible,
        ignore_base_visibility=True,
    )

    assert canvas.main_visible(visible)
    assert not canvas.main_visible(hidden)
    assert canvas._shape_hit_candidates(QtCore.QPointF(280, 60)) == []
    canvas.select_shapes([hidden], source="canvas")
    assert canvas.selected_shapes == []
    canvas._set_size_overlay_hover_shape(hidden)
    assert canvas._size_overlay_hover_shape is None
    boxed = shapes_intersecting_rect(
        canvas.shapes,
        QtCore.QRectF(240, 20, 100, 100),
        canvas.is_shape_interactive,
    )
    assert boxed == []

    canvas.close()
    canvas.deleteLater()
    qapp.processEvents()


def test_hold_preview_draws_other_rounds_but_keeps_them_read_only(
    qapp: QtWidgets.QApplication,
) -> None:
    """All-preview changes paint eligibility without changing hit testing."""
    canvas = DensityReviewCanvas(preview_shortcut="V")
    canvas.resize(400, 200)
    canvas.load_pixmap(_pixmap())
    current = _rectangle("current", 20, 20, 70, 90)
    other = _rectangle("other", 250, 30, 320, 100)
    canvas.load_shapes([current, other])
    canvas.set_round([current.xanylabeling_shape_id], None)

    assert canvas.main_visible(current)
    assert not canvas.main_visible(other)
    press = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_V,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(canvas, press)
    assert canvas.main_visible(other)
    assert not canvas.is_shape_interactive(other)
    assert canvas._shape_hit_candidates(QtCore.QPointF(280, 60)) == []
    release = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyRelease,
        QtCore.Qt.Key.Key_V,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(canvas, release)
    assert not canvas.main_visible(other)

    canvas.close()
    canvas.deleteLater()
    qapp.processEvents()


def test_live_edit_shared_undo_redo_and_lock(
    review_host: tuple[_Host, DensityRoundReviewCoordinator],
) -> None:
    """Review edits update main data and share one reversible history."""
    host, controller = review_host
    source = host.canvas.shapes[0]
    shape_id = source.xanylabeling_shape_id
    projection = controller._review_map[shape_id]
    original_left = source.points[0].x()

    controller._on_review_edit_started((shape_id,))
    projection.move_by(QtCore.QPointF(15, 0))
    controller._on_review_shape_changed(projection)
    controller._on_review_edit_finished((shape_id,), True)
    assert source.points[0].x() == original_left + 15

    controller.undo()
    assert host.canvas.shapes[0].points[0].x() == original_left
    controller.redo()
    assert host.canvas.shapes[0].points[0].x() == original_left + 15

    controller._locks[shape_id] = "main"
    assert not controller._can_edit(shape_id, "review")


def test_main_selection_requires_confirmation_and_round_keeps_viewport(
    review_host: tuple[_Host, DensityRoundReviewCoordinator],
) -> None:
    """Main selection is pending until confirmation and does not refit views."""
    host, controller = review_host
    window = controller.window
    assert window is not None
    target = host.canvas.shapes[1]
    expected_round = controller.session.round_for(target.xanylabeling_shape_id)
    assert expected_round == 1
    initial_round = controller.session.current_round

    host.canvas.select_shapes([target], source="canvas")
    assert controller.session.current_round == initial_round
    assert controller._pending_main_ids == (target.xanylabeling_shape_id,)

    window.canvas.scale = 2.25
    controller.sync_main_selection()
    assert controller.session.current_round == expected_round
    assert window.canvas.scale == 2.25
    assert [
        shape.xanylabeling_shape_id for shape in window.canvas.selected_shapes
    ] == [target.xanylabeling_shape_id]


def test_visibility_and_geometry_restore_without_enabled_state(
    review_host: tuple[_Host, DensityRoundReviewCoordinator],
) -> None:
    """Review overrides are transient while geometry and last file persist."""
    host, controller = review_host
    hidden = host.canvas.shapes[0]
    hidden.visible = False
    hidden.hidden_by_filter = True
    assert host.canvas.main_visible(hidden)
    assert controller.window is not None
    controller.window.resize(920, 640)

    controller.disable()

    assert not host.canvas.main_visible(hidden)
    assert host.settings.value("density_round_review/geometry") is not None
    assert (
        host.settings.value("density_round_review/last_filename") == "0001.jpg"
    )
    assert not controller.active


def test_review_shortcuts_are_configured_and_guard_bar_editors(
    review_host: tuple[_Host, DensityRoundReviewCoordinator],
) -> None:
    """Navigation shortcuts do not fire while a compact-bar field is edited."""
    _host, controller = review_host
    window = controller.window
    assert window is not None
    sequences = {shortcut.key().toString() for shortcut in window._shortcuts}
    assert {"[", "]", "F10", "0", "1", "9"}.issubset(sequences)
    calls = []
    digit_calls = []
    window.previous_requested.connect(lambda: calls.append("previous"))
    window.digit_requested.connect(digit_calls.append)

    window.limit_spin.setFocus()
    window._activate_shortcut(window.previous_requested)
    window._activate_digit_shortcut(3)
    assert calls == []
    assert digit_calls == []
    window.canvas.setFocus()
    window._activate_shortcut(window.previous_requested)
    window._activate_digit_shortcut(3)
    assert calls == ["previous"]
    assert digit_calls == [3]


def test_review_display_follows_main_but_masks_stay_disabled(
    review_host: tuple[_Host, DensityRoundReviewCoordinator],
) -> None:
    """Information display mirrors the main Canvas except for masks."""
    host, controller = review_host
    window = controller.window
    assert window is not None
    host.canvas.show_texts = False
    host.canvas.show_labels = False
    host.canvas.show_scores = False
    host.canvas.show_masks = True
    host.canvas.label_display_mode = "description"

    controller.sync_display_from_main()

    assert not window.canvas.show_texts
    assert not window.canvas.show_labels
    assert not window.canvas.show_scores
    assert window.canvas.label_display_mode == "description"
    assert not window.canvas.show_masks
    assert window.canvas.appearance_settings is host.appearance_settings
    assert (
        window.canvas.appearance_label_colors == host.appearance_label_colors
    )


def test_failed_save_keeps_may_continue_blocked(monkeypatch) -> None:
    """Choosing Save must not permit navigation when saving still failed."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    fake = SimpleNamespace(
        dirty=True,
        filename="0001.jpg",
        tr=lambda text: text,
        save_file=lambda: None,
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *_args, **_kwargs: (QtWidgets.QMessageBox.StandardButton.Save),
    )

    assert not LabelingWidget.may_continue(fake)


def test_failed_auto_save_marks_document_dirty() -> None:
    """An unsuccessful automatic save must block the next image change."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    save_action = SimpleNamespace(setEnabled=lambda _enabled: None)
    undo_action = SimpleNamespace(setEnabled=lambda _enabled: None)
    fake = SimpleNamespace(
        _config={"auto_save": True},
        actions=SimpleNamespace(save=save_action, undo=undo_action),
        canvas=SimpleNamespace(is_shape_restorable=True),
        image_path="0001.jpg",
        output_dir=None,
        save_labels=lambda _filename: False,
        dirty=False,
    )

    LabelingWidget.set_dirty(fake)

    assert fake.dirty


def test_real_labeling_widget_action_opens_review_window(
    qapp: QtWidgets.QApplication,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The configured main-window action activates a real review session."""
    from anylabeling.config import get_default_config
    from anylabeling.services.auto_labeling import model_manager
    from anylabeling.views.labeling import label_widget as label_widget_module

    config = copy.deepcopy(get_default_config())
    config["auto_save"] = False
    config["rename_shortcuts"] = {1: {"label": "reading"}}
    monkeypatch.setattr(
        label_widget_module, "save_config", lambda _config: None
    )
    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    image_path = tmp_path / "0001.png"
    image = QtGui.QImage(400, 200, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(image_path))

    main_window = QtWidgets.QMainWindow()
    wrapper = QtWidgets.QWidget()
    wrapper.parent = main_window
    widget = label_widget_module.LabelingWidget(
        parent=wrapper,
        config=config,
    )
    try:
        assert widget.load_file(str(image_path))
        widget.load_shapes(
            [_rectangle("person", 20, 20, 70, 90)], replace=True
        )
        widget.actions.toggle_density_round_review.trigger()
        qapp.processEvents()

        controller = widget.density_round_review_controller
        assert controller.active
        assert controller.window is not None
        assert controller.window.isVisible()
        assert controller.session.current_members == (
            widget.canvas.shapes[0].xanylabeling_shape_id,
        )
        widget.set_canvas_params("show_texts", False)
        widget.set_canvas_params("show_masks", True)
        assert not controller.window.canvas.show_texts
        assert not controller.window.canvas.show_masks

        projection = controller._review_map[
            widget.canvas.shapes[0].xanylabeling_shape_id
        ]
        controller.window.canvas.select_shapes(
            [projection], source="review_test"
        )
        assert not controller._editing_active()
        assert widget.digit_rename_manager.rename_shortcuts[1] == {
            "label": "reading"
        }
        assert widget.canvas.selected_shapes == [widget.canvas.shapes[0]]
        assert controller._locks == {}
        assert (
            controller._main_map()[projection.xanylabeling_shape_id]
            is widget.canvas.shapes[0]
        )
        controller.window.canvas.setFocus()
        controller.window._activate_digit_shortcut(1)
        assert widget.canvas.shapes[0].label == "reading"
        assert (
            controller._review_map[
                widget.canvas.shapes[0].xanylabeling_shape_id
            ].label
            == "reading"
        )

        widget.undo_shape_edit()
        assert widget.canvas.shapes[0].label == "person"
        controller.redo()
        assert widget.canvas.shapes[0].label == "reading"
    finally:
        widget.density_round_review_controller.disable()
        widget.dirty = False
        widget.close()
        widget.deleteLater()
        wrapper.deleteLater()
        main_window.deleteLater()
        qapp.processEvents()
