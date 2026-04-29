"""Viewport state management for canvas view persistence across image switches.

This module provides a lightweight, coordinate-system-agnostic way to save and
restore the user's view position (zoom + center point) when navigating between
images. It is designed for the QWidget-based Canvas architecture in
X-AnyLabeling 4.0.0-beta.4 (PyQt6).

The core idea is to store the view centre in **image coordinates** rather than
scrollbar pixel values, so the state survives widget-resize events and is
portable across images of different sizes.

Usage in LabelWidget.load_file()::

    # 1. Save current view before leaving the image
    self.viewport_controller.on_file_leaving(
        filename=self.viewport_controller.last_loaded,
        canvas=self.canvas,
        zoom_widget=self.zoom_widget,
        zoom_mode=self.zoom_mode,
    )

    # 2. Load new pixmap
    will_restore = self.viewport_controller.resolve(filename, keep_prev) is not None
    self.canvas.load_pixmap(image, clear_shapes=clear_shapes)
    if not will_restore:
        self.adjust_scale(initial=True)

    # 3. Restore view for the new image (if we have one)
    restored = self.viewport_controller.on_file_loaded(
        filename=filename,
        canvas=self.canvas,
        zoom_widget=self.zoom_widget,
        keep_prev_viewport=self._config.get("keep_prev_viewport", False),
    )
    if restored:
        self.zoom_mode = restored.zoom_mode
        self.zoom_values[filename] = (restored.zoom_mode, restored.zoom_value)
    else:
        # fallback to old logic
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6 import QtCore
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QScrollArea

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from anylabeling.views.labeling.widgets.canvas import Canvas
    from anylabeling.views.labeling.widgets.zoom_widget import ZoomWidget


@dataclass
class ViewportState:
    """Immutable snapshot of the user's view.

    Attributes:
        zoom_mode: 0 = FIT_WINDOW, 1 = FIT_WIDTH, 2 = MANUAL_ZOOM.
        zoom_value: Zoom percentage, e.g. 150 for 150%.
        center_x: X coordinate of the view centre in **image coordinates**.
        center_y: Y coordinate of the view centre in **image coordinates**.
    """

    zoom_mode: int
    zoom_value: int
    center_x: float
    center_y: float


class ViewportController:
    """Manages per-image viewport persistence.

    The controller stores a mapping ``filename → ViewportState`` and exposes
    lifecycle hooks that should be called around ``LabelWidget.load_file()``.
    """

    # Zoom mode constants (mirroring LabelWidget)
    FIT_WINDOW = 0
    FIT_WIDTH = 1
    MANUAL_ZOOM = 2

    def __init__(self) -> None:
        self._states: dict[str, ViewportState] = {}
        self._last_loaded: str | None = None

    # --------------------------------------------------------------------- #
    # Public properties
    # --------------------------------------------------------------------- #

    @property
    def states(self) -> dict[str, ViewportState]:
        """Direct access to the internal state map (for debugging)."""
        return self._states

    @property
    def last_loaded(self) -> str | None:
        """Filename of the image that was most recently *successfully* loaded.

        Updated by :meth:`on_file_loaded`.  Used by ``LabelWidget`` to know
        which file's state should be saved when switching away.
        """
        return self._last_loaded

    # --------------------------------------------------------------------- #
    # Lifecycle hooks
    # --------------------------------------------------------------------- #

    def on_file_leaving(
        self,
        filename: str | None,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        zoom_mode: int,
    ) -> None:
        """Call **before** leaving an image (e.g. at the top of ``load_file``).

        Unconditionally saves the current viewport state so that returning to
        this image later restores the exact same view.
        """
        if not filename:
            return
        state = self._capture(canvas, zoom_widget, zoom_mode)
        if state is not None:
            self._states[filename] = state

    def on_file_loaded(
        self,
        filename: str,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        keep_prev_viewport: bool,
    ) -> ViewportState | None:
        """Call **after** a new image has been loaded.

        Resolves the best available ``ViewportState`` and applies it to the
        canvas.  Returns the applied state, or ``None`` if no state was found
        (caller should fall back to ``adjust_scale``).

        The resolution priority is:
        1. Exact history for *filename*.
        2. If ``keep_prev_viewport`` is ``True``, inherit the previous image's
           state (useful when batch-processing a folder of same-size images).
        3. No state → return ``None``.
        """
        state = self._resolve(filename, keep_prev_viewport)
        if state is not None:
            self._apply(state, canvas, zoom_widget)

        self._last_loaded = filename
        return state

    # --------------------------------------------------------------------- #
    # Core API
    # --------------------------------------------------------------------- #

    def capture(
        self,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        zoom_mode: int,
    ) -> ViewportState | None:
        """Public convenience wrapper around :meth:`_capture`."""
        return self._capture(canvas, zoom_widget, zoom_mode)

    def resolve(
        self,
        filename: str,
        keep_prev_viewport: bool,
    ) -> ViewportState | None:
        """Public convenience wrapper around :meth:`_resolve`."""
        return self._resolve(filename, keep_prev_viewport)

    def apply(
        self,
        state: ViewportState,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
    ) -> None:
        """Public convenience wrapper around :meth:`_apply`."""
        self._apply(state, canvas, zoom_widget)

    def has_state(self, filename: str) -> bool:
        """Return ``True`` if we have a saved state for *filename*."""
        return filename in self._states

    def clear(self) -> None:
        """Drop all saved states (e.g. on ``File → Close Folder``)."""
        self._states.clear()
        self._last_loaded = None

    def clear_state(self, filename: str) -> bool:
        """清除指定图片的视口状态。

        如果清除的文件是 ``_last_loaded``，则同时置空 ``_last_loaded``，
        防止 ``keep_prev_viewport`` 继承已失效的状态。
        """
        if filename not in self._states:
            return False
        del self._states[filename]
        if self._last_loaded == filename:
            self._last_loaded = None
        return True

    def clear_states(self, filenames) -> int:
        """批量清除多张图片的视口状态。

        返回实际清除的数量。
        """
        count = 0
        for filename in filenames:
            if self.clear_state(filename):
                count += 1
        return count

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _capture(
        self,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        zoom_mode: int,
    ) -> ViewportState | None:
        """Sample the current viewport and return a ``ViewportState``.

        Returns ``None`` when the canvas has no valid pixmap.
        """
        pixmap = canvas.pixmap
        if pixmap is None or pixmap.isNull() or pixmap.width() == 0:
            return None

        # Zoom value is always available from the widget
        zoom_value = int(zoom_widget.value())

        # Convert scrollbar-centric view into image-coordinate centre.
        #
        # In the QWidget Canvas architecture the visible area is controlled by
        # the QScrollArea scrollbars.  The relationship is:
        #
        #   viewport centre (widget coords) =
        #       scroll_value + viewport_size/2
        #
        #   image coordinate = widget_coord / scale - offset_to_center()
        #
        # We ask the parent scroll area for the scrollbar values because the
        # Canvas itself does not hold them.
        # Note: QScrollArea.setWidget() reparents the canvas to the viewport
        # widget, so we must walk up the parent chain to find the QScrollArea.
        scroll_area = canvas.parentWidget()
        while scroll_area is not None and not isinstance(
            scroll_area, QScrollArea
        ):
            scroll_area = scroll_area.parentWidget()
        if scroll_area is None:
            return None

        h_bar = scroll_area.horizontalScrollBar()
        v_bar = scroll_area.verticalScrollBar()

        # widget coordinate of the viewport centre
        viewport_w = scroll_area.viewport().width()
        viewport_h = scroll_area.viewport().height()
        widget_cx = h_bar.value() + viewport_w / 2.0
        widget_cy = v_bar.value() + viewport_h / 2.0

        # transform to image coordinates (same formula as Canvas.transform_pos)
        scale = canvas.scale
        offset = canvas.offset_to_center()
        center_x = widget_cx / scale - offset.x()
        center_y = widget_cy / scale - offset.y()

        return ViewportState(
            zoom_mode=zoom_mode,
            zoom_value=zoom_value,
            center_x=center_x,
            center_y=center_y,
        )

    def _resolve(
        self,
        filename: str,
        keep_prev_viewport: bool,
    ) -> ViewportState | None:
        """Pick the best available state for *filename*."""
        # 1. Exact history
        if filename in self._states:
            return self._states[filename]

        # 2. Inherit previous image's view
        if keep_prev_viewport and self._last_loaded in self._states:
            return self._states[self._last_loaded]

        return None

    def _apply(
        self,
        state: ViewportState,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
    ) -> None:
        """Apply *state* to *canvas* in a single atomic transformation.

        The sequence is:
        1. Set zoom (block signals to avoid side-effects).
        2. Compute where the saved image-centre maps to in widget coords.
        3. Adjust scrollbars so that point lands at the viewport centre.
        """
        pixmap = canvas.pixmap
        if pixmap is None or pixmap.isNull() or pixmap.width() == 0:
            return

        # --- 1. Set zoom ---
        zoom_widget.blockSignals(True)
        zoom_widget.setValue(state.zoom_value)
        zoom_widget.blockSignals(False)

        # The zoom widget change does **not** automatically resize the canvas
        # in this architecture; we must set the canvas scale explicitly.
        canvas.scale = state.zoom_value / 100.0
        canvas.adjustSize()
        canvas.update()

        # --- 2. Scroll to the saved centre ---
        scroll_area = canvas.parentWidget()
        while scroll_area is not None and not isinstance(
            scroll_area, QScrollArea
        ):
            scroll_area = scroll_area.parentWidget()
        if scroll_area is None:
            return

        h_bar = scroll_area.horizontalScrollBar()
        v_bar = scroll_area.verticalScrollBar()

        viewport_w = scroll_area.viewport().width()
        viewport_h = scroll_area.viewport().height()

        # Image centre → widget centre (inverse of capture logic)
        offset = canvas.offset_to_center()
        widget_cx = (state.center_x + offset.x()) * canvas.scale
        widget_cy = (state.center_y + offset.y()) * canvas.scale

        # Scroll so that widget_cx/y is at the viewport centre
        target_h = int(widget_cx - viewport_w / 2.0)
        target_v = int(widget_cy - viewport_h / 2.0)

        # Clamp to valid scrollbar range
        target_h = max(h_bar.minimum(), min(h_bar.maximum(), target_h))
        target_v = max(v_bar.minimum(), min(v_bar.maximum(), target_v))

        h_bar.setValue(target_h)
        v_bar.setValue(target_v)
