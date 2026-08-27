"""Qt adapter for the pure-Python virtual review page session."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from PyQt6 import QtCore, QtWidgets

from ...virtual_review import (
    VirtualPackingOptions,
    VirtualPackingResult,
    VirtualReviewSession,
    VirtualShapeView,
    VirtualTaskCriteria,
    build_virtual_tasks,
    fit_scale,
    pack_virtual_tasks,
    union_bboxes,
)


class VirtualReviewController(QtCore.QObject):
    """Coordinate virtual pages, Canvas focus, and viewport navigation."""

    status_changed = QtCore.pyqtSignal(str)

    def __init__(self, label_widget, review_widget) -> None:
        """Initialize the controller and connect review controls."""
        super().__init__(label_widget)
        self._label_widget = label_widget
        self._canvas = label_widget.canvas
        self._review_widget = review_widget
        self._session = VirtualReviewSession()
        self._criteria: Optional[VirtualTaskCriteria] = None
        self._packing_options = VirtualPackingOptions()
        self._packing_result: Optional[VirtualPackingResult] = None
        self._shape_map: dict[str, Any] = {}
        self._captured_viewport = None
        self._overview = False
        self._dataset_mode = False
        review_widget.start_requested.connect(self.start)
        review_widget.stop_requested.connect(self.stop)
        review_widget.previous_requested.connect(self.previous)
        review_widget.next_requested.connect(self.next)
        review_widget.overview_requested.connect(self.toggle_overview)

    @property
    def active(self) -> bool:
        """Return whether a virtual session has active pages."""
        return self._session.active

    def _shape_runtime_id(self, shape: Any, index: int) -> str:
        """Return a fallback runtime identity for non-persistent Shapes."""
        value = getattr(shape, "_virtual_review_id", None)
        if not value:
            value = f"vr:{index}:{uuid.uuid4().hex}"
            shape._virtual_review_id = value
        return str(value)

    def _shape_tracking_id(self, shape: Any, index: int) -> str:
        """Prefer the persistent Shape identity for review tracking."""
        value = getattr(shape, "xanylabeling_shape_id", None)
        if isinstance(value, str) and value:
            return value
        return self._shape_runtime_id(shape, index)

    def _shape_views(self) -> tuple[VirtualShapeView, ...]:
        """Adapt current Canvas shapes to pure task-builder views."""
        self._shape_map = {}
        claimed_ids: set[str] = set()
        views = []
        for index, shape in enumerate(self._canvas.shapes):
            shape_id = self._shape_tracking_id(shape, index)
            if shape_id in claimed_ids:
                shape._virtual_review_id = None
                shape_id = self._shape_runtime_id(shape, index)
            shape._virtual_review_tracking_id = shape_id
            claimed_ids.add(shape_id)
            self._shape_map[shape_id] = shape
            try:
                rect = shape.bounding_rect()
                bbox = (
                    float(rect.x()),
                    float(rect.y()),
                    float(rect.x() + rect.width()),
                    float(rect.y() + rect.height()),
                )
                width = float(rect.width())
                height = float(rect.height())
            except (AttributeError, IndexError, TypeError, ValueError):
                bbox = None
                width = height = None
            views.append(
                VirtualShapeView(
                    shape_id=shape_id,
                    label=str(getattr(shape, "label", "") or ""),
                    shape_type=str(getattr(shape, "shape_type", "") or ""),
                    group_id=getattr(shape, "group_id", None),
                    width=width,
                    height=height,
                    bbox=bbox,
                    base_visible=self._canvas.base_visible(shape),
                )
            )
        return tuple(views)

    def _viewport_size(self) -> tuple[float, float]:
        """Return the current review viewport size, failing closed to 0."""
        scroll_area = getattr(self._label_widget, "_central_widget", None)
        viewport = getattr(scroll_area, "viewport", None)
        if viewport is None:
            return (0.0, 0.0)
        size = viewport().size()
        return (float(size.width()), float(size.height()))

    def _build_packing_result(self) -> VirtualPackingResult:
        """Build atomic tasks and pack them into frozen pages."""
        tasks = build_virtual_tasks(self._shape_views(), self._criteria)
        return pack_virtual_tasks(
            tasks, self._viewport_size(), self._packing_options
        )

    def start(self, payload: dict) -> None:
        """Generate and activate a page list from UI criteria."""
        dataset_controller = getattr(
            self._label_widget, "dataset_review_controller", None
        )
        if dataset_controller is not None and getattr(
            dataset_controller, "session_active", False
        ):
            self._set_status(
                "数据集复核队列进行中：请先关闭队列再使用单图复核"
            )
            return
        if self._canvas.drawing() or getattr(
            self._canvas, "rect_edge_dragging", False
        ):
            self._set_status("请先完成或取消当前绘制/拖动操作")
            return
        criteria_payload = (
            payload.get("criteria", {}) if isinstance(payload, dict) else {}
        )
        packing_payload = (
            payload.get("packing", {}) if isinstance(payload, dict) else {}
        )
        if not isinstance(criteria_payload, dict) or not isinstance(
            packing_payload, dict
        ):
            self._set_status("条件无效：生成参数格式错误")
            return
        try:
            criteria = VirtualTaskCriteria(**criteria_payload)
            packing_options = VirtualPackingOptions(**packing_payload)
        except (TypeError, ValueError) as exc:
            self._set_status(f"条件无效：{exc}")
            return
        was_active = self.active
        self._criteria = criteria
        self._packing_options = packing_options
        self._packing_result = self._build_packing_result()
        if not was_active:
            self._captured_viewport = self._capture_viewport()
        result = self._session.start(self._packing_result.pages)
        self._overview = False
        if result.page is None:
            if was_active:
                self.stop()
            else:
                self._label_widget._virtual_review_active = False
                self._captured_viewport = None
            self._review_widget.set_running(False)
            self._set_status("当前图片没有符合条件的目标")
            return
        self._label_widget._virtual_review_active = True
        self._clear_conflicting_focus()
        self._review_widget.set_running(True)
        self._publish_packing_stats()
        self._activate_current()

    def stop(self) -> None:
        """End the session and restore normal Canvas state."""
        if not self.active and self._captured_viewport is None:
            return
        self._canvas.clear_virtual_review_visibility_predicate()
        self._label_widget._virtual_review_active = False
        if self._captured_viewport is not None:
            self._restore_viewport(self._captured_viewport)
        self._captured_viewport = None
        self._overview = False
        self._packing_result = None
        self._session.stop()
        self._review_widget.set_running(False)
        self._review_widget.set_progress(-1, 0)
        self._set_status("目标复核已退出")

    def previous(self) -> None:
        """Navigate to the previous page."""
        self._move(-1)

    def next(self) -> None:
        """Navigate to the next page."""
        self._move(1)

    def _move(self, delta: int) -> None:
        """Move the session cursor after checking transient edit state."""
        if not self.active:
            return
        if self._is_edit_transaction_active():
            self._set_status("请先完成或取消当前编辑操作")
            return
        available = set(self._current_shape_map())
        result = self._session.move(delta, available)
        if result.boundary:
            self._set_status("已经是第一页" if delta < 0 else "已经是最后一页")
            return
        self._overview = False
        self._activate_current()
        if result.skipped_page_ids:
            self._set_status("已跳过已删除的目标")

    def toggle_overview(self) -> None:
        """Toggle read-only full-image context for the active page."""
        if not self.active:
            return
        self._overview = not self._overview
        if self._overview:
            # Keep the virtual predicate installed so unrelated shapes remain
            # non-interactive; only the camera changes to the full image.
            self._label_widget.set_fit_window()
            self._set_status("全图查看：当前页面仍保持只读焦点")
        else:
            self._activate_current()

    def on_image_loaded(self) -> None:
        """Rebuild pages for a newly loaded image when mode stays active."""
        if self._dataset_mode:
            # Dataset queue mode owns page activation; the queued page
            # is installed by its controller after load completes.
            return
        if self._criteria is None or not self.active:
            return
        self._captured_viewport = self._capture_viewport()
        self._packing_result = self._build_packing_result()
        result = self._session.start(self._packing_result.pages)
        self._overview = False
        if result.page is None:
            self._canvas.clear_virtual_review_visibility_predicate()
            self._label_widget._virtual_review_active = False
            self._captured_viewport = None
            self._session.stop()
            self._review_widget.set_running(False)
            self._set_status("新图片没有符合条件的目标")
            return
        self._review_widget.set_running(True)
        self._publish_packing_stats()
        self._activate_current()

    def _current_shape_map(self) -> dict[str, Any]:
        """Return current shapes keyed by persistent-or-fallback identities."""
        self._shape_views()
        return self._shape_map

    def _publish_packing_stats(self) -> None:
        """Push packing diagnostics to the review panel."""
        result = self._packing_result
        if result is None:
            return
        self._review_widget.set_packing_stats(
            atomic_tasks=result.atomic_task_count,
            pages=result.page_count,
            fallback=result.singleton_fallback_count,
        )

    def _activate_current(self) -> None:
        """Install the current page predicate and focus its viewport."""
        page = self._session.current
        if page is None:
            return
        shape_map = self._current_shape_map()
        available = set(shape_map)
        if not any(anchor_id in available for anchor_id in page.anchor_ids):
            result = self._session.move(1, available)
            if result.page is None or result.boundary:
                self._set_status("当前页面锚点已全部删除")
                return
            page = result.page
        self._install_page(page)

    def _install_page(self, page) -> None:
        """Install one page's focus predicate and viewport framing.

        Shared by the local session and dataset queue mode so both
        modes apply identical Canvas ownership behavior.
        """

        shape_map = self._current_shape_map()
        member_ids = frozenset(
            shape_id for shape_id in page.member_ids if shape_id in shape_map
        )
        if member_ids:
            self._canvas.set_virtual_review_visibility_predicate(
                lambda shape: getattr(
                    shape, "_virtual_review_tracking_id", None
                )
                in member_ids
            )
        anchor_id = next(
            (
                anchor_id
                for anchor_id in page.anchor_ids
                if anchor_id in shape_map
            ),
            None,
        )
        anchor = shape_map.get(anchor_id) if anchor_id else None
        if anchor is not None and not self._is_edit_transaction_active():
            self._canvas.deselect_shape()
            self._canvas.select_shapes([anchor])
        self._center_on_page(page, shape_map)
        surviving_tasks = sum(
            1 for page_anchor in page.anchor_ids if page_anchor in shape_map
        )
        self._review_widget.set_progress(
            self._session.index,
            len(self._session.pages),
            surviving_tasks,
        )
        self._review_widget.set_running(True)

    # ── dataset queue mode (cross-file review) ────────────────

    @property
    def dataset_mode_active(self) -> bool:
        """Return whether dataset queue mode owns the review focus."""

        return self._dataset_mode

    def enter_dataset_mode(self) -> None:
        """Hand the review focus layer to the dataset queue controller.

        Exits any local session first so the two modes never control
        Canvas focus simultaneously, then captures the pre-session
        viewport once for later restore.
        """

        if self._dataset_mode:
            return
        if self.active:
            self.stop()
        self._dataset_mode = True
        self._captured_viewport = self._capture_viewport()
        self._label_widget._virtual_review_active = True
        self._clear_conflicting_focus()
        self._review_widget.set_running(False)
        self._review_widget.set_progress(-1, 0)

    def exit_dataset_mode(self) -> None:
        """Release the focus layer and restore the pre-session viewport."""

        if not self._dataset_mode:
            return
        self._dataset_mode = False
        self._canvas.clear_virtual_review_visibility_predicate()
        self._label_widget._virtual_review_active = False
        if self._captured_viewport is not None:
            self._restore_viewport(self._captured_viewport)
        self._captured_viewport = None
        self._review_widget.set_running(False)
        self._review_widget.set_progress(-1, 0)

    def install_dataset_page(self, page, progress: tuple) -> bool:
        """Activate one externally supplied frozen page.

        Returns whether at least one member shape is live; the dataset
        controller uses the result to accept or reject activation.
        ``progress`` is ``(index, total, live_tasks)`` for display.
        """

        if not self._dataset_mode:
            return False
        shape_map = self._current_shape_map()
        if not any(shape_id in shape_map for shape_id in page.member_ids):
            return False
        self._install_page(page)
        self._review_widget.set_progress(*progress)
        return True

    def review_viewport_size(self) -> tuple:
        """Return the current review viewport size for queue builds."""

        return self._viewport_size()

    def dataset_shape_payloads(self) -> tuple:
        """Return views, points, and shapes for queue rehydration.

        Points are included because task-content signatures are
        computed from quantized points at build time; the runtime
        rehydration must use the same source to produce equal
        signatures.
        """

        views = self._shape_views()
        points_by_id: dict[str, tuple] = {}
        for view in views:
            shape = self._shape_map.get(view.shape_id)
            raw_points = getattr(shape, "points", None) or ()
            try:
                points_by_id[view.shape_id] = tuple(
                    (float(point.x()), float(point.y()))
                    for point in raw_points
                )
            except (AttributeError, TypeError, ValueError):
                points_by_id[view.shape_id] = ()
        return views, points_by_id, dict(self._shape_map)

    def _center_on_page(self, page, shape_map: dict[str, Any]) -> None:
        """Center and fit the surviving page union with a fit margin."""
        bbox = union_bboxes(
            (
                self._rect_bbox(shape_map[shape_id].bounding_rect())
                if shape_id in shape_map
                else None
            )
            for shape_id in page.member_ids
        )
        if bbox is None:
            return
        left, top, right, bottom = bbox
        margin = self._packing_options.fit_margin
        scroll_area = self._label_widget._central_widget
        viewport = scroll_area.viewport().size()
        scale = fit_scale(
            bbox,
            (float(viewport.width()), float(viewport.height())),
            margin,
        )
        if scale <= 0:
            return
        self._label_widget.set_zoom(int(round(scale * 100.0)))
        self._canvas.scale = self._label_widget.zoom_widget.value() / 100.0
        self._canvas.adjustSize()
        pixmap = self._canvas.pixmap
        if pixmap is None or pixmap.isNull():
            return
        cx = (left + right) / 2.0 / pixmap.width()
        cy = (top + bottom) / 2.0 / pixmap.height()
        canvas_size = self._canvas.size()
        self._label_widget.set_scroll(
            QtCore.Qt.Orientation.Horizontal,
            cx * canvas_size.width() - viewport.width() / 2.0,
        )
        self._label_widget.set_scroll(
            QtCore.Qt.Orientation.Vertical,
            cy * canvas_size.height() - viewport.height() / 2.0,
        )

    def _capture_viewport(self):
        """Capture the current transient viewport state."""
        result = self._label_widget.viewport_controller.capture_result(
            self._canvas,
            self._label_widget.zoom_widget,
            self._label_widget.zoom_mode,
        )
        return result.state if result.success else None

    def _restore_viewport(self, state) -> None:
        """Restore a previously captured viewport state."""
        result = self._label_widget.viewport_controller.apply_result(
            state,
            self._canvas,
            self._label_widget.zoom_widget,
        )
        if result.success:
            self._label_widget._sync_viewport_ui(state)

    def prepare_image_change(self) -> None:
        """Restore the pre-session viewport before image-load persistence."""
        if self._captured_viewport is not None:
            self._restore_viewport(self._captured_viewport)

    @staticmethod
    def _rect_bbox(rect) -> tuple[float, float, float, float]:
        """Convert a Qt rectangle to the pure-model bbox representation."""
        left = float(rect.x())
        top = float(rect.y())
        return (
            left,
            top,
            left + float(rect.width()),
            top + float(rect.height()),
        )

    def _clear_conflicting_focus(self) -> None:
        """Clear existing geometry focus before installing page focus."""
        clear_focus = getattr(
            self._label_widget, "_clear_rect_refine_focus", None
        )
        if clear_focus is not None:
            clear_focus()

    def _is_edit_transaction_active(self) -> bool:
        """Return whether navigation could interrupt a live edit."""
        return bool(
            self._canvas.drawing()
            or getattr(self._canvas, "rect_edge_dragging", False)
            or getattr(self._canvas, "moving_shape", False)
            or QtWidgets.QApplication.activeModalWidget() is not None
        )

    def _set_status(self, message: str) -> None:
        """Publish a status message to the review panel and LabelWidget."""
        self._review_widget.progress_label.setText(message)
        self._label_widget.status(message)
        self.status_changed.emit(message)


__all__ = ["VirtualReviewController"]
