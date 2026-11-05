import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtTest, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    # Let begin_session() create the target from the template; an empty
    # pre-created file would make the persisted baseline differ from the
    # in-memory template of the window and turn startup saves into conflicts.
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    template = copy.deepcopy(load_template_config())
    user_config.begin_session(
        target_path=str(config_file),
        origin="file",
        template=copy.deepcopy(template),
        effective=copy.deepcopy(template),
        ensure_created=True,
        normalizer=normalize_user_config,
    )
    window = MainWindow(app, config=copy.deepcopy(load_template_config()))
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    window.labeling_widget.view.error_message = lambda *args, **kwargs: None
    yield window
    window.labeling_widget.view.dirty = False
    window.close()
    app.removeEventFilter(window.labeling_widget.view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    user_config.end_session()


def image_path(tmp_path, name, color="white", size=(64, 64)):
    path = tmp_path / name
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_opacity_retention_across_images(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "a.png", "red")
    second = image_path(tmp_path, "b.png", "blue")

    assert widget.load_file(first)
    panel.opacity_slider.setValue(40)
    assert widget.canvas.shape_opacity == pytest.approx(0.4)

    panel.opacity_pin.setChecked(False)
    assert widget.load_file(second)
    assert panel.opacity_slider.value() == 100
    assert widget.canvas.shape_opacity == pytest.approx(1.0)

    panel.opacity_slider.setValue(40)
    assert widget.load_file(first)
    assert panel.opacity_slider.value() == 100

    panel.opacity_slider.setValue(40)
    assert widget.load_file(first)
    assert panel.opacity_slider.value() == 40
    assert widget.canvas.shape_opacity == pytest.approx(0.4)

    panel.opacity_pin.setChecked(True)
    assert widget.load_file(second)
    assert panel.opacity_slider.value() == 40
    assert widget.canvas.shape_opacity == pytest.approx(0.4)


def test_failed_load_does_not_apply_retention(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "a.png")

    assert widget.load_file(first)
    panel.opacity_pin.setChecked(False)
    panel.opacity_slider.setValue(35)

    assert not widget.load_file(str(tmp_path / "missing.png"))
    assert panel.opacity_slider.value() == 35
    assert widget.canvas.shape_opacity == pytest.approx(0.35)


def test_cancel_navigation_keeps_display_values(window, tmp_path, monkeypatch):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "a.png")
    second = image_path(tmp_path, "b.png")
    assert widget.load_file(first)
    widget.file_list_widget.addItem(first)
    widget.file_list_widget.addItem(second)
    widget.fn_to_index[first] = 0
    widget.fn_to_index[second] = 1
    panel.opacity_pin.setChecked(False)
    panel.opacity_slider.setValue(35)
    monkeypatch.setattr(widget, "may_continue", lambda: False)

    widget.open_next_image()

    assert widget.filename == first
    assert panel.opacity_slider.value() == 35
    assert widget.canvas.shape_opacity == pytest.approx(0.35)


def test_traditional_mode_pan_uses_scrollbars(window, tmp_path):
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "large.png", size=(1600, 1200))
    assert widget.load_file(path)
    widget.set_zoom(150)
    widget.apply_wheel_navigation_mode("traditional")
    widget.canvas.pan_offset = QtCore.QPointF()
    for bar in widget.scroll_bars.values():
        bar.setValue(0)

    widget.pan_canvas(QtCore.QPointF(80, -60))

    assert widget.canvas.pan_offset.isNull()
    assert any(bar.value() != 0 for bar in widget.scroll_bars.values())


def test_brightness_contrast_cache_and_keep_actions(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "a.png", "red")
    second = image_path(tmp_path, "b.png", "blue")
    third = image_path(tmp_path, "c.png", "green")

    assert widget.load_file(first)
    widget._on_inline_brightness_contrast(70, 80)
    panel.set_brightness_contrast(70, 80)
    assert widget.brightness_contrast_values[first] == (70, 80)

    assert widget.load_file(second)
    assert panel.brightness_slider.value() == 50
    assert panel.contrast_slider.value() == 50

    widget._on_inline_brightness_contrast(60, 90)
    assert widget.load_file(first)
    assert panel.brightness_slider.value() == 70
    assert panel.contrast_slider.value() == 80

    widget.actions.keep_prev_brightness.trigger()
    widget.actions.keep_prev_contrast.trigger()
    assert panel.brightness_pin.isChecked()
    assert panel.contrast_pin.isChecked()

    assert widget.load_file(third)
    assert panel.brightness_slider.value() == 70
    assert panel.contrast_slider.value() == 80

    panel.brightness_pin.click()
    assert not widget.actions.keep_prev_brightness.isChecked()
    assert not widget._config["keep_prev_brightness"]


@pytest.mark.parametrize("axis", ["brightness", "contrast"])
@pytest.mark.parametrize(
    "error",
    [
        user_config.ConfigLockBusy("another instance holds the lock"),
        user_config.ConfigConflict(["keep_prev"]),
        user_config.ConfigWriteError("no space left on device"),
    ],
    ids=["lock-busy", "conflict", "write-failed"],
)
def test_failed_keep_save_restores_action_and_pin_together(
    window, tmp_path, monkeypatch, axis, error
):
    """A failed write must not leave the menu on while config stays off."""
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    key = f"keep_prev_{axis}"
    action = getattr(widget.actions, key)
    pin = getattr(panel, f"{axis}_pin")
    assert not action.isChecked()
    assert not pin.isChecked()

    def fail_save(*args, **kwargs):
        raise error

    original_save = user_config.save_patch
    monkeypatch.setattr(user_config, "save_patch", fail_save)
    pin.click()

    assert widget._config[key] is False
    assert not action.isChecked()
    assert not pin.isChecked()

    # Once saving works again the same button applies the value everywhere.
    monkeypatch.setattr(user_config, "save_patch", original_save)
    pin.click()

    assert widget._config[key] is True
    assert action.isChecked()
    assert pin.isChecked()


def test_failed_keep_scale_save_restores_the_menu_action(
    window, tmp_path, monkeypatch
):
    widget = window.labeling_widget.view
    action = widget.actions.keep_prev_scale
    assert not action.isChecked()

    def fail_save(*args, **kwargs):
        raise user_config.ConfigWriteError("read-only configuration")

    original_save = user_config.save_patch
    monkeypatch.setattr(user_config, "save_patch", fail_save)
    action.trigger()

    assert widget._config["keep_prev_scale"] is False
    assert not action.isChecked()

    monkeypatch.setattr(user_config, "save_patch", original_save)
    action.trigger()

    assert widget._config["keep_prev_scale"] is True
    assert action.isChecked()


@pytest.mark.parametrize("axis", ["brightness", "contrast"])
def test_pending_value_is_kept_when_switching_before_throttle(
    window, tmp_path, axis
):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "a.png", "red")
    second = image_path(tmp_path, "b.png", "blue")
    assert widget.load_file(first)

    if axis == "brightness":
        widget.actions.keep_prev_brightness.trigger()
        slider = panel.brightness_slider
    else:
        widget.actions.keep_prev_contrast.trigger()
        slider = panel.contrast_slider
    slider.setValue(90)
    assert panel._bc_update_timer.isActive()

    assert widget.load_file(second)
    assert not panel._bc_update_timer.isActive()
    assert slider.value() == 90

    expected = (90, 50) if axis == "brightness" else (50, 90)
    assert widget.brightness_contrast_values[first] == expected
    target = widget.brightness_contrast_values[second]
    assert (target[0] if axis == "brightness" else target[1]) == 90

    QtTest.QTest.qWait(panel.BC_UPDATE_INTERVAL_MS + 30)
    assert slider.value() == 90


def test_pending_brightness_update_cannot_leak_into_next_image(
    window, tmp_path
):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "a.png", "red")
    second = image_path(tmp_path, "b.png", "blue")

    assert widget.load_file(first)
    panel.brightness_slider.setValue(90)
    assert panel._bc_update_timer.isActive()
    assert widget.load_file(second)

    assert not panel._bc_update_timer.isActive()
    assert panel.brightness_slider.value() == 50
    assert widget.brightness_contrast_values[second] == (None, None)


def test_display_changes_keep_zoom_and_pan(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    path = image_path(tmp_path, "a.png")

    assert widget.load_file(path)
    widget.set_zoom(175)
    widget.pan_canvas(QtCore.QPointF(35, -20))
    scale = widget.canvas.scale
    pan = QtCore.QPointF(widget.canvas.pan_offset)
    backups = len(widget.canvas.shapes_backups)

    panel.opacity_slider.setValue(25)
    widget._on_inline_brightness_contrast(75, 65)

    assert widget.canvas.scale == pytest.approx(scale)
    assert widget.canvas.pan_offset == pan
    assert len(widget.canvas.shapes_backups) == backups
    assert not widget.dirty


def test_wheel_navigation_mode_switch_preserves_the_view(window, tmp_path):
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "large.png", size=(1600, 1200))
    assert widget.load_file(path)
    widget.set_zoom(150)
    widget.pan_canvas(QtCore.QPointF(60, -40))
    before = widget._current_shared_view()

    widget.apply_wheel_navigation_mode("traditional")
    assert widget.canvas.wheel_navigation_mode == "traditional"
    assert (
        widget._canvas_scroll_area.horizontalScrollBarPolicy()
        == QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    after = widget._current_shared_view()
    assert after.zoom_value == pytest.approx(before.zoom_value)
    assert after.center_x == pytest.approx(before.center_x, abs=2)
    assert after.center_y == pytest.approx(before.center_y, abs=2)
    # Traditional mode must not keep a hidden free pan behind the snapshot.
    assert widget.canvas.pan_offset.isNull()

    widget.apply_wheel_navigation_mode("direct")
    assert widget.canvas.wheel_navigation_mode == "direct"
    assert (
        widget._canvas_scroll_area.horizontalScrollBarPolicy()
        == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    restored = widget._current_shared_view()
    assert restored.zoom_value == pytest.approx(before.zoom_value)
    assert restored.center_x == pytest.approx(before.center_x, abs=2)
    assert restored.center_y == pytest.approx(before.center_y, abs=2)


def _assert_pan_inside_scroll_range(widget):
    for orientation, bar in widget.scroll_bars.items():
        assert bar.minimum() <= bar.value() <= bar.maximum(), orientation


def test_traditional_mode_switch_clamps_an_unreachable_pan_at_once(
    window, tmp_path
):
    """A pan beyond the image edge must clamp during the switch itself."""
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "large.png", size=(1600, 1200))
    assert widget.load_file(path)
    widget.set_zoom(150)
    # Pan far enough that traditional mode cannot reproduce the centre.
    widget.pan_canvas(QtCore.QPointF(900, 600))
    scale = widget.canvas.scale
    viewport = widget._canvas_scroll_area.viewport()

    widget.apply_wheel_navigation_mode("traditional")

    assert widget.canvas.pan_offset.isNull()
    _assert_pan_inside_scroll_range(widget)
    clamped = widget._current_shared_view()
    assert clamped.zoom_value == pytest.approx(150)
    # The left/top image edge is the only reachable view for that centre.
    assert clamped.center_x == pytest.approx(
        (viewport.width() / 2.0) / scale, abs=2
    )
    assert clamped.center_y == pytest.approx(
        (viewport.height() / 2.0) / scale, abs=2
    )

    # The next tiny gesture must not teleport the now-clamped view.
    widget.pan_canvas(QtCore.QPointF(1, 1))
    nudged = widget._current_shared_view()
    assert nudged.center_x == pytest.approx(clamped.center_x, abs=1e-6)
    assert nudged.center_y == pytest.approx(clamped.center_y, abs=1e-6)


def test_traditional_mode_switch_folds_a_reachable_pan_into_scrollbars(
    window, tmp_path
):
    """A reachable pan becomes scroll positions without moving the image."""
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "large.png", size=(1600, 1200))
    assert widget.load_file(path)
    widget.set_zoom(150)
    widget.pan_canvas(QtCore.QPointF(60, -40))
    before = widget._current_shared_view()
    scale = widget.canvas.scale

    widget.apply_wheel_navigation_mode("traditional")

    assert widget.canvas.pan_offset.isNull()
    _assert_pan_inside_scroll_range(widget)
    after = widget._current_shared_view()
    assert after.center_x == pytest.approx(before.center_x, abs=2)
    assert after.center_y == pytest.approx(before.center_y, abs=2)

    # One pixel of pan moves one pixel instead of replaying the whole pan.
    widget.pan_canvas(QtCore.QPointF(1, 0))
    nudged = widget._current_shared_view()
    assert widget.canvas.pan_offset.isNull()
    assert nudged.center_x == pytest.approx(after.center_x - 1.0 / scale, abs=0.1)
    assert nudged.center_y == pytest.approx(after.center_y, abs=0.1)

    # A small zoom step keeps the anchored centre and leaves no hidden pan.
    widget.add_zoom(0.9)
    zoomed = widget._current_shared_view()
    assert widget.canvas.pan_offset.isNull()
    _assert_pan_inside_scroll_range(widget)
    assert zoomed.center_x == pytest.approx(nudged.center_x, abs=2)
    assert zoomed.center_y == pytest.approx(nudged.center_y, abs=2)


def test_traditional_mode_same_size_switch_keeps_view_without_hidden_pan(
    window, tmp_path
):
    widget = window.labeling_widget.view
    first = image_path(tmp_path, "first.png", "red", size=(1600, 1200))
    second = image_path(tmp_path, "second.png", "blue", size=(1600, 1200))
    assert widget.load_file(first)
    widget.apply_wheel_navigation_mode("traditional")
    widget.set_zoom(150)
    QtWidgets.QApplication.processEvents()
    widget.pan_canvas(QtCore.QPointF(120, 90))
    QtWidgets.QApplication.processEvents()
    before = widget._current_shared_view()
    scale = widget.canvas.scale

    assert widget.load_file(second)
    QtWidgets.QApplication.processEvents()

    assert widget.canvas.pan_offset.isNull()
    _assert_pan_inside_scroll_range(widget)
    after = widget._current_shared_view()
    assert after.zoom_value == pytest.approx(before.zoom_value)
    assert after.center_x == pytest.approx(before.center_x, abs=2)
    assert after.center_y == pytest.approx(before.center_y, abs=2)

    widget.pan_canvas(QtCore.QPointF(1, 0))
    nudged = widget._current_shared_view()
    assert nudged.center_x == pytest.approx(after.center_x - 1.0 / scale, abs=0.1)
    assert nudged.center_y == pytest.approx(after.center_y, abs=0.1)


def test_traditional_mode_different_size_switch_leaves_no_hidden_pan(
    window, tmp_path
):
    widget = window.labeling_widget.view
    large = image_path(tmp_path, "large.png", size=(1600, 1200))
    small = image_path(tmp_path, "small.png", size=(500, 400))
    assert widget.load_file(large)
    widget.apply_wheel_navigation_mode("traditional")
    widget.set_zoom(150)
    widget.pan_canvas(QtCore.QPointF(120, 90))

    assert widget.load_file(small)
    QtWidgets.QApplication.processEvents()

    assert widget.canvas.pan_offset.isNull()
    _assert_pan_inside_scroll_range(widget)
    before = widget._current_shared_view()
    widget.pan_canvas(QtCore.QPointF(1, 0))
    after = widget._current_shared_view()
    # No jump: a one pixel pan moves at most one widget pixel.
    assert abs(after.center_x - before.center_x) <= 1.0 / widget.canvas.scale + 1e-6
    assert widget.canvas.pan_offset.isNull()


def test_wheel_navigation_mode_waits_for_active_edit(window, tmp_path):
    from anylabeling.views.labeling.shape import Shape

    widget = window.labeling_widget.view
    path = image_path(tmp_path, "a.png")
    assert widget.load_file(path)
    widget.canvas.current = Shape(shape_type="rectangle")

    widget.apply_wheel_navigation_mode("traditional")
    assert widget.canvas.wheel_navigation_mode == "direct"
    assert widget._pending_wheel_navigation_mode == "traditional"

    widget.canvas.current = None
    widget._apply_pending_wheel_navigation_mode()
    assert widget.canvas.wheel_navigation_mode == "traditional"
    assert widget._pending_wheel_navigation_mode is None


def _start_extreme_draft(widget):
    creation = widget.rectangle_creation
    creation.start_extreme()
    draft = creation.draft
    assert draft is not None
    assert draft.accept(30, 20)
    assert widget.canvas.interaction_in_progress()
    return creation


def test_wheel_mode_waits_for_extreme_draft_and_applies_after_cancel(
    window, tmp_path
):
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "a.png")
    assert widget.load_file(path)
    creation = _start_extreme_draft(widget)

    widget.apply_wheel_navigation_mode("traditional")
    assert widget.canvas.wheel_navigation_mode == "direct"
    assert widget._pending_wheel_navigation_mode == "traditional"

    creation.cancel()
    QtWidgets.QApplication.processEvents()
    assert widget.canvas.wheel_navigation_mode == "traditional"
    assert widget._pending_wheel_navigation_mode is None


def test_wheel_mode_waits_for_extreme_draft_and_applies_after_submit(
    window, tmp_path
):
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "a.png")
    assert widget.load_file(path)
    creation = _start_extreme_draft(widget)
    draft = creation.draft
    assert draft.accept(60, 30)
    assert draft.accept(55, 60)
    assert draft.accept(10, 55)
    assert draft.complete

    widget.apply_wheel_navigation_mode("traditional")
    assert widget.canvas.wheel_navigation_mode == "direct"

    widget.digit_to_label = "object"
    creation.submit_draft()
    QtWidgets.QApplication.processEvents()
    assert widget.canvas.wheel_navigation_mode == "traditional"
    assert widget._pending_wheel_navigation_mode is None


def test_runtime_applier_switches_wheel_mode(window, tmp_path):
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "a.png", size=(1600, 1200))
    assert widget.load_file(path)

    widget._settings_runtime_applier.apply_change(
        "canvas.wheel_navigation_mode", "traditional"
    )

    assert widget.canvas.wheel_navigation_mode == "traditional"
    assert widget._config["canvas"]["wheel_navigation_mode"] == "traditional"


def test_reset_buttons_do_not_change_retention(window, tmp_path):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    path = image_path(tmp_path, "a.png")
    assert widget.load_file(path)

    panel.opacity_pin.setChecked(False)
    panel.opacity_slider.setValue(0)
    reset = next(
        button
        for button in panel.findChildren(QtWidgets.QToolButton)
        if button.toolTip() == "Reset to default"
        and button.parent() is panel.content_widget
    )
    reset.click()
    assert panel.opacity_slider.value() == 100
    assert not panel.opacity_pin.isChecked()
