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
import logging
import math
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QScrollArea

from anylabeling.views.labeling.widgets.viewport_state_machine import (
    ViewportLoadPlan,
    ViewportResetResult,
    ViewportSource,
    ViewportState,
    ViewportStateMachine,
    ViewportStateSnapshot,
)

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from anylabeling.views.labeling.widgets.canvas import Canvas
    from anylabeling.views.labeling.widgets.zoom_widget import ZoomWidget


ViewportResetSnapshot = ViewportStateSnapshot
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ViewportCaptureResult:
    """Result of sampling a Qt canvas viewport."""

    success: bool
    state: ViewportState | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ViewportApplyResult:
    """Result of applying a viewport state to Qt widgets."""

    success: bool
    state: ViewportState | None = None
    reason: str | None = None


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
        self._state_machine = ViewportStateMachine()

    # --------------------------------------------------------------------- #
    # Public properties
    # --------------------------------------------------------------------- #

    @property
    def states(self) -> dict[str, ViewportState]:
        """Return a copy of exact states for diagnostics and migration."""
        return dict(self._state_machine.debug_snapshot())

    @property
    def force_default_on_next_load(self) -> set[str]:
        """Return a copy of pending default identities."""
        return set(self._state_machine.pending_defaults())

    @property
    def last_loaded(self) -> str | None:
        """Filename of the image that was most recently *successfully* loaded.

        Updated by :meth:`on_file_loaded`.  Used by ``LabelWidget`` to know
        which file's state should be saved when switching away.
        """
        return self._state_machine.active_file_id

    # --------------------------------------------------------------------- #
    # Lifecycle hooks
    # --------------------------------------------------------------------- #

    def on_file_leaving(
        self,
        filename: str | None,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        zoom_mode: int,
    ) -> ViewportCaptureResult:
        """Call **before** leaving an image (e.g. at the top of ``load_file``).

        Unconditionally saves the current viewport state so that returning to
        this image later restores the exact same view.
        """
        if not filename:
            return ViewportCaptureResult(False, reason="missing_filename")
        result = self.capture_result(canvas, zoom_widget, zoom_mode)
        if result.success and result.state is not None:
            self._state_machine.capture(filename, result.state)
        return result

    def on_file_loaded(
        self,
        filename: str,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        keep_prev_viewport: bool,
        keep_prev_scale: bool = False,
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
        plan = self.resolve_load_plan(
            filename,
            keep_prev_viewport=keep_prev_viewport,
            keep_prev_scale=keep_prev_scale,
        )
        if plan.source is ViewportSource.FORCE_DEFAULT:
            return None
        if plan.state is None:
            self._state_machine.commit_loaded(
                filename, plan, applied_zoom=int(zoom_widget.value())
            )
            return None
        result = self.apply_result(plan.state, canvas, zoom_widget)
        if not result.success:
            return None
        self._state_machine.commit_loaded(filename, plan)
        return plan.state

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

    def capture_result(
        self,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
        zoom_mode: int,
    ) -> ViewportCaptureResult:
        """Capture a viewport and expose a structured result."""
        try:
            state = self._capture(canvas, zoom_widget, zoom_mode)
        except (
            AttributeError,
            TypeError,
            ValueError,
            ZeroDivisionError,
        ) as exc:
            return ViewportCaptureResult(False, reason=str(exc))
        if state is None:
            return ViewportCaptureResult(False, reason="invalid_canvas")
        return ViewportCaptureResult(True, state=state)

    def resolve(
        self,
        filename: str,
        keep_prev_viewport: bool,
    ) -> ViewportState | None:
        """Public convenience wrapper around :meth:`_resolve`."""
        return self._resolve(filename, keep_prev_viewport)

    def resolve_load_plan(
        self,
        filename: str,
        *,
        keep_prev_viewport: bool,
        keep_prev_scale: bool = False,
    ) -> ViewportLoadPlan:
        """Return the pure state-machine plan for a file load."""
        plan = self._state_machine.resolve_load_plan(
            filename,
            keep_prev_viewport=keep_prev_viewport,
            keep_prev_scale=keep_prev_scale,
        )
        logger.debug(
            "Viewport load plan file=%s source=%s",
            filename,
            plan.source.value,
        )
        return plan

    def commit_loaded(
        self,
        filename: str,
        plan: ViewportLoadPlan,
        *,
        applied_zoom: int | None = None,
    ) -> str:
        """Commit a load plan after its Qt application succeeds."""
        file_id = self._state_machine.commit_loaded(
            filename,
            plan,
            applied_zoom=applied_zoom,
        )
        if self.last_loaded != file_id:
            raise AssertionError("active viewport file did not commit")
        return file_id

    def commit_default_loaded(
        self, filename: str, *, applied_zoom: int | None = None
    ) -> str:
        """Commit a safe default fallback as the active loaded file."""
        file_id = self.normalize_filename(filename)
        if file_id is None:
            raise ValueError("filename must be a non-empty path")
        plan = ViewportLoadPlan(file_id, ViewportSource.DEFAULT)
        return self.commit_loaded(
            filename,
            plan,
            applied_zoom=applied_zoom,
        )

    def apply(
        self,
        state: ViewportState,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
    ) -> ViewportApplyResult:
        """Public convenience wrapper around :meth:`_apply`."""
        return self.apply_result(state, canvas, zoom_widget)

    def apply_result(
        self,
        state: ViewportState,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
    ) -> ViewportApplyResult:
        """Apply a state and report whether the complete operation succeeded."""
        try:
            applied = self._apply(state, canvas, zoom_widget)
        except (
            AttributeError,
            TypeError,
            ValueError,
            ZeroDivisionError,
        ) as exc:
            return ViewportApplyResult(False, state=state, reason=str(exc))
        if not applied:
            return ViewportApplyResult(
                False, state=state, reason="invalid_canvas"
            )
        return ViewportApplyResult(True, state=state)

    def has_state(self, filename: str) -> bool:
        """Return ``True`` if we have a saved state for *filename*."""
        return self._state_machine.get_state(filename) is not None

    def state_for(self, filename: str) -> ViewportState | None:
        """Return one exact state without exposing internal storage."""
        return self._state_machine.get_state(filename)

    @staticmethod
    def normalize_filename(filename: str | None) -> str | None:
        """Return the canonical identity used by the state machine."""
        return ViewportStateMachine.normalize_file_id(filename)

    def record_state(self, filename: str, state: ViewportState) -> str:
        """Record a validated state for migration tests and adapters."""
        return self._state_machine.capture(filename, state)

    def clear(self) -> None:
        """Drop all saved states (e.g. on ``File → Close Folder``)."""
        self._state_machine.clear_session()

    def clear_state(self, filename: str) -> bool:
        """清除指定图片的视口状态。

        如果清除的文件是 ``_last_loaded``，则同时置空 ``_last_loaded``，
        防止 ``keep_prev_viewport`` 继承已失效的状态。
        """
        return self._state_machine.clear_file(filename)

    def reset_states(
        self, filenames, *, mark_default: bool = True
    ) -> ViewportResetResult:
        """Invalidate viewport state for a unique sequence of filenames.

        Args:
            filenames: Iterable of image filenames to reset.
            mark_default: Whether each target must bypass inherited state on
                its next load.

        Returns:
            A summary separating requested targets from removed cache entries.
        """
        return self._state_machine.reset(
            filenames,
            mark_default=mark_default,
        )

    def reset_states_with_rollback(
        self,
        filenames,
        *,
        mark_default: bool = True,
        after_reset=None,
    ) -> ViewportResetResult:
        """Reset files and roll back if the coordinating callback fails."""
        return self._state_machine.reset_with_rollback(
            filenames,
            mark_default=mark_default,
            after_reset=after_reset,
        )

    def snapshot_reset_state(self, filenames) -> ViewportResetSnapshot:
        """Capture target state before a multi-cache reset transaction."""
        return self._state_machine.snapshot(filenames)

    def restore_reset_state(self, snapshot: ViewportResetSnapshot) -> None:
        """Restore a snapshot captured before a failed reset transaction."""
        self._state_machine.restore(snapshot)

    def consume_force_default(self, filename: str) -> bool:
        """Consume a pending default-view marker for *filename*."""
        return self._state_machine.consume_reset_pending(filename)

    @staticmethod
    def _normalize_filenames(filenames) -> tuple[str, ...]:
        """Return unique non-empty string filenames in stable order."""
        return ViewportStateMachine._normalize_filenames(filenames)

    def clear_states(self, filenames) -> int:
        """批量清除多张图片的视口状态。

        返回实际清除的数量。
        """
        return sum(self.clear_state(filename) for filename in filenames)

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

        Returns ``None`` when the canvas has no valid pixmap or scroll area.
        """
        pixmap = canvas.pixmap
        if pixmap is None or pixmap.isNull() or pixmap.width() == 0:
            return None

        # Zoom value is always available from the widget.
        zoom_value = int(zoom_widget.value())
        if zoom_value <= 0 or canvas.scale <= 0:
            return None

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
        return self.resolve_load_plan(
            filename,
            keep_prev_viewport=keep_prev_viewport,
            keep_prev_scale=False,
        ).state

    def _apply(
        self,
        state: ViewportState,
        canvas: Canvas,
        zoom_widget: ZoomWidget,
    ) -> bool:
        """Apply *state* to *canvas* in a single atomic transformation.

        The sequence is:
        1. Set zoom (block signals to avoid side-effects).
        2. Compute where the saved image-centre maps to in widget coords.
        3. Adjust scrollbars so that point lands at the viewport centre.
        """
        pixmap = canvas.pixmap
        if pixmap is None or pixmap.isNull() or pixmap.width() == 0:
            return False
        try:
            scroll_area = canvas.parentWidget()
            while scroll_area is not None and not isinstance(
                scroll_area, QScrollArea
            ):
                scroll_area = scroll_area.parentWidget()
            if scroll_area is None:
                return False
            if state.zoom_value <= 0:
                return False
            if not math.isfinite(state.center_x) or not math.isfinite(
                state.center_y
            ):
                return False
            h_bar = scroll_area.horizontalScrollBar()
            v_bar = scroll_area.verticalScrollBar()
            viewport_w = scroll_area.viewport().width()
            viewport_h = scroll_area.viewport().height()
            old_zoom = int(zoom_widget.value())
            old_scale = float(canvas.scale)
            old_h = h_bar.value()
            old_v = v_bar.value()
        except (AttributeError, TypeError, ValueError):
            return False

        signals_blocked = False
        try:
            # The zoom widget change does not resize this Canvas by itself.
            signals_blocked = True
            zoom_widget.blockSignals(True)
            zoom_widget.setValue(state.zoom_value)
            zoom_widget.blockSignals(False)
            signals_blocked = False

            canvas.scale = state.zoom_value / 100.0
            canvas.adjustSize()

            # Image centre → widget centre (inverse of capture logic).
            offset = canvas.offset_to_center()
            widget_cx = (state.center_x + offset.x()) * canvas.scale
            widget_cy = (state.center_y + offset.y()) * canvas.scale
            target_h = int(widget_cx - viewport_w / 2.0)
            target_v = int(widget_cy - viewport_h / 2.0)

            # Clamp to valid scrollbar ranges.
            target_h = max(h_bar.minimum(), min(h_bar.maximum(), target_h))
            target_v = max(v_bar.minimum(), min(v_bar.maximum(), target_v))
            h_bar.setValue(target_h)
            v_bar.setValue(target_v)
            canvas.update()
            return True
        except (AttributeError, TypeError, ValueError, RuntimeError):
            # Roll back the small UI snapshot so a partial restore is never
            # reported as success.
            try:
                if signals_blocked:
                    zoom_widget.blockSignals(False)
                zoom_widget.blockSignals(True)
                zoom_widget.setValue(old_zoom)
                zoom_widget.blockSignals(False)
                canvas.scale = old_scale
                canvas.adjustSize()
                h_bar.setValue(old_h)
                v_bar.setValue(old_v)
                canvas.update()
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
            return False
