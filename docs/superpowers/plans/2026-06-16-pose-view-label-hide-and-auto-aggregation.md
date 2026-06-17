# Pose View 标签隐藏与自动聚合模式修改实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify Pose View to hide all native Canvas labels while keeping PoseRenderer overlay independent; make `show_labels` also control Pose labels; refactor auto-focus aggregation into a clear ARMED/FOCUSED/OFF state machine; ensure non-interactive/hidden shapes cannot be hovered, selected, or edited; and keep the left label list in sync with `hidden_by_filter`.

**Architecture:** Introduce `Canvas.is_shape_interactive()` and `Canvas._should_draw_standard_label()` as single gates; move `PoseRenderer.render()` out of the `show_labels` block and pass `show_labels` into it; add `LabelingWidget.auto_focus_group_id`, rewrite `toggle_auto_focus_instance()` / `_auto_focus_on_selection()` / ESC handling; add `_sync_label_list_hidden_by_filter()` to hide rows in the label list.

**Tech Stack:** PyQt6, Python 3.x, pytest, black, flake8

---

## Task 1: Canvas – add interaction and standard-label gates

**Files:**
- Modify: `anylabeling/views/labeling/widgets/canvas.py` (~lines 480-482)

- [ ] **Step 1: Add `is_shape_interactive()` and `_should_draw_standard_label()`**

Insert immediately after the existing `is_visible()` method:

```python
def is_shape_interactive(self, shape):
    """Return whether a shape can be hovered, selected, or edited."""
    return (
        self.is_visible(shape)
        and getattr(shape, "visible", True)
        and not getattr(shape, "hidden_by_filter", False)
    )

def _should_draw_standard_label(self, shape):
    """Return whether the standard Canvas label should be drawn."""
    if not self.show_labels:
        return False
    if self.pose_config.enabled:
        return False
    if not self.is_shape_interactive(shape):
        return False
    return True
```

- [ ] **Step 2: Verify the helper uses existing attributes**

No test yet; just confirm `self.visible`, `shape.visible`, and `shape.hidden_by_filter` exist and the methods compile.

---

## Task 2: Canvas – guard all interaction entry points

**Files:**
- Modify: `anylabeling/views/labeling/widgets/canvas.py`

- [ ] **Step 3: Guard hover entry point**

Around line 844 change:

```python
for shape in reversed([s for s in self.shapes if self.is_visible(s)]):
```

to:

```python
for shape in reversed(
    [s for s in self.shapes if self.is_shape_interactive(s)]
):
```

- [ ] **Step 4: Guard double-click edit label entry point**

Around line 1404 change:

```python
for shape in reversed(self.shapes):
    if not self.is_visible(shape):
        continue
```

to:

```python
for shape in reversed(self.shapes):
    if not self.is_shape_interactive(shape):
        continue
```

- [ ] **Step 5: Guard `select_shape_point()` entry point**

Around line 1492 change:

```python
for shape in reversed(self.shapes):
    if not self.is_visible(shape):
        continue
```

to:

```python
for shape in reversed(self.shapes):
    if not self.is_shape_interactive(shape):
        continue
```

- [ ] **Step 6: Filter programmatic `select_shapes()`**

Around line 1437 change:

```python
def select_shapes(self, shapes):
    """Select some shapes"""
    self.set_hiding()
    self.selection_changed.emit(shapes)
    self.update()
```

to:

```python
def select_shapes(self, shapes):
    """Select some shapes"""
    interactive_shapes = [
        s for s in shapes if self.is_shape_interactive(s)
    ]
    self.set_hiding()
    self.selection_changed.emit(interactive_shapes)
    self.update()
```

---

## Task 3: Canvas – restructure label drawing and PoseRenderer call

**Files:**
- Modify: `anylabeling/views/labeling/widgets/canvas.py` (~lines 2682-2957)

- [ ] **Step 7: Move hover-context computation before the `show_labels` block**

Extract `hovered_group` and `zoom_reveals` so both native labels and PoseRenderer can use them. Replace the start of the label block:

```python
        # Draw labels
        if self.show_labels:
            p.setFont(
                QtGui.QFont(
                    "Arial", int(max(6.0, int(round(8.0 / Shape.scale))))
                )
            )
            labels = []
            # Compute hover context once for the unified label gate.
            hovered_shape = self.h_hape
            mp = self.prev_move_point
            if hovered_shape is None:
                for s in self.shapes:
                    if (
                        s.shape_type == "point"
                        and s.points
                        and s.visible
                        and not getattr(s, "hidden_by_filter", False)
                    ):
                        if (
                            math.hypot(
                                mp.x() - s.points[0].x(),
                                mp.y() - s.points[0].y(),
                            )
                            * self.scale
                            <= 10
                        ):
                            hovered_shape = s
                            break
            hovered_group = (
                hovered_shape.group_id if hovered_shape is not None else None
            )
            zoom_reveals = self.scale >= self.label_zoom_threshold
```

with:

```python
        # Compute hover context once for the unified label gate.
        hovered_shape = self.h_hape
        mp = self.prev_move_point
        if hovered_shape is None:
            for s in self.shapes:
                if (
                    s.shape_type == "point"
                    and s.points
                    and self.is_shape_interactive(s)
                ):
                    if (
                        math.hypot(
                            mp.x() - s.points[0].x(),
                            mp.y() - s.points[0].y(),
                        )
                        * self.scale
                        <= 10
                    ):
                        hovered_shape = s
                        break
        hovered_group = (
            hovered_shape.group_id if hovered_shape is not None else None
        )
        zoom_reveals = self.scale >= self.label_zoom_threshold

        # Draw labels
        if self.show_labels and not self.pose_config.enabled:
            p.setFont(
                QtGui.QFont(
                    "Arial", int(max(6.0, int(round(8.0 / Shape.scale))))
                )
            )
            labels = []
```

- [ ] **Step 8: Replace Pose View special-case skip with the new gate**

Around line 2715 change:

```python
            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                # Pose View: skip COCO keypoint points and person rects.
                if self.pose_config.enabled:
                    if (
                        shape.shape_type == "point"
                        and shape.label in COCO_KEYPOINT_SET
                    ):
                        continue
                    if (
                        shape.shape_type == "rectangle"
                        and shape.label == "person"
                        and shape.group_id is not None
                    ):
                        continue
```

to:

```python
            for shape in self.shapes:
                if not self._should_draw_standard_label(shape):
                    continue
```

- [ ] **Step 9: Move `PoseRenderer.render()` out of the `show_labels` block**

Change the PoseRenderer call site (around line 2940) from:

```python
            # Pose View overlay (after standard labels).
            if (
                self.pose_config.enabled
                and self.pixmap is not None
                and self._has_pose_shapes()
            ):
                count = self._pose_renderer.render(
                    p,
                    self.shapes,
                    self.pixmap.size(),
                    self.scale,
                    label_on_selection=self.label_on_selection,
                    hovered_group_id=hovered_group,
                    zoom_reveals=zoom_reveals,
                )
                if count != self.pose_config.occlusion_count:
                    self.pose_config.occlusion_count = count
                    self.pose_occlusion_count_changed.emit(count)
```

to:

```python
        # Pose View overlay (after standard labels).
        if (
            self.pose_config.enabled
            and self.pixmap is not None
            and self._has_pose_shapes()
        ):
            count = self._pose_renderer.render(
                p,
                self.shapes,
                self.pixmap.size(),
                self.scale,
                show_labels=self.show_labels,
                label_on_selection=self.label_on_selection,
                hovered_group_id=hovered_group,
                zoom_reveals=zoom_reveals,
            )
            if count != self.pose_config.occlusion_count:
                self.pose_config.occlusion_count = count
                self.pose_occlusion_count_changed.emit(count)
```

Ensure the indentation moves it outside the `if self.show_labels and not self.pose_config.enabled:` block but keeps it inside `paintEvent`.

---

## Task 4: PoseRenderer – accept `show_labels` to control pose label overlay

**Files:**
- Modify: `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py`

- [ ] **Step 10: Add `show_labels` parameter to `render()`**

Change the signature (around line 156):

```python
def render(
    self,
    painter: QtGui.QPainter,
    shapes: List[Any],
    pixmap_size: QtCore.QSize,
    scale: float,
    label_on_selection: bool = False,
    hovered_group_id: Optional[int] = None,
    zoom_reveals: bool = False,
) -> int:
```

to:

```python
def render(
    self,
    painter: QtGui.QPainter,
    shapes: List[Any],
    pixmap_size: QtCore.QSize,
    scale: float,
    show_labels: bool = True,
    label_on_selection: bool = False,
    hovered_group_id: Optional[int] = None,
    zoom_reveals: bool = False,
) -> int:
```

- [ ] **Step 11: Use `show_labels` to skip pose label drawing**

Change (around line 212):

```python
            self._draw_keypoints(painter, kp_shapes, cfg, pi, scale)
            if show_labels:
                items = self._build_label_items(kp_shapes, mid, cfg, pi, scale)
                items, overlap = apply_layout(
                    items,
                    mid,
                    bbox,
                    cfg.layout_mode,
                    leader_length=cfg.leader_length / scale,
                    column_gap=cfg.column_gap / scale,
                )
                total_overlap += overlap
                self._draw_labels(painter, items, cfg, scale)
```

No further change needed; skeleton, bbox, and keypoints still render when `show_labels=False`.

---

## Task 5: LabelWidget – filter label-list selection and sync row visibility

**Files:**
- Modify: `anylabeling/views/labeling/label_widget.py`

- [ ] **Step 12: Filter label-list selection through `is_shape_interactive()`**

Around line 6425 change:

```python
    def label_selection_changed(self):
        if self._no_selection_slot:
            return
        if self.canvas.editing():
            selected_shapes = []
            for item in self.label_list.selected_items():
                selected_shapes.append(item.shape())
            if selected_shapes:
                self.canvas.select_shapes(selected_shapes)
            else:
                self.canvas.deselect_shape()
```

to:

```python
    def label_selection_changed(self):
        if self._no_selection_slot:
            return
        if self.canvas.editing():
            selected_shapes = []
            for item in self.label_list.selected_items():
                shape = item.shape()
                if self.canvas.is_shape_interactive(shape):
                    selected_shapes.append(shape)
            if selected_shapes:
                self.canvas.select_shapes(selected_shapes)
            else:
                self.canvas.deselect_shape()
```

- [ ] **Step 13: Add label-list row-hiding helper**

Insert near the other instance-visibility helpers (after `show_all_instances`, around line 7437):

```python
    def _sync_label_list_hidden_by_filter(self):
        """Show/hide label-list rows based on shape.hidden_by_filter."""
        selection_model = self.label_list.selectionModel()
        blocker = QtCore.QSignalBlocker(selection_model)
        try:
            for row in range(self.label_list.model().rowCount()):
                item = self.label_list.model().item(row, 0)
                if item is None:
                    continue
                shape = item.shape()
                is_hidden = getattr(shape, "hidden_by_filter", False)
                self.label_list.setRowHidden(row, is_hidden)
                if is_hidden:
                    index = self.label_list.model().indexFromItem(item)
                    if selection_model.isSelected(index):
                        selection_model.select(
                            index,
                            QtCore.QItemSelectionModel.SelectionFlag.Deselect,
                        )
        finally:
            del blocker
```

- [ ] **Step 14: Update `show_all_instances()` to restore label-list rows**

Change (around line 7432):

```python
    def show_all_instances(self):
        """Show all instances"""
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = False
        self.canvas.update()
        self.status(self.tr("All instances visible"))
```

to:

```python
    def show_all_instances(self):
        """Show all instances"""
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = False
        self.canvas.update()
        self._sync_label_list_hidden_by_filter()
        self.status(self.tr("All instances visible"))
```

---

## Task 6: LabelWidget – refactor auto-focus state machine

**Files:**
- Modify: `anylabeling/views/labeling/label_widget.py`

- [ ] **Step 15: Add `auto_focus_group_id` state**

Around line 7386 change:

```python
        # Alt+H: Toggle auto-focus instance mode
        self.auto_focus_instance = False
```

to:

```python
        # Alt+H: Toggle auto-focus instance mode
        self.auto_focus_instance = False
        self.auto_focus_group_id = None
```

- [ ] **Step 16: Rewrite `toggle_auto_focus_instance()`**

Change (around line 7439):

```python
    def toggle_auto_focus_instance(self):
        """Toggle auto-focus instance aggregation mode."""
        self.auto_focus_instance = not self.auto_focus_instance
        if self.auto_focus_instance:
            self.status(
                self.tr("自动聚合模式已开启（选中即聚焦，ESC 退出聚合）"), 3000
            )
        else:
            self.show_all_instances()
            self.status(self.tr("自动聚合模式已关闭"), 2000)
```

to:

```python
    def toggle_auto_focus_instance(self):
        """Toggle auto-focus instance aggregation mode."""
        if self.auto_focus_instance:
            self.auto_focus_instance = False
            self.auto_focus_group_id = None
            self.show_all_instances()
            self.status(self.tr("自动聚合模式已关闭"), 2000)
        else:
            self.auto_focus_instance = True
            self.auto_focus_group_id = None
            self.status(
                self.tr("自动聚合已开启，选择目标后聚焦"), 3000
            )
```

- [ ] **Step 17: Rewrite `_auto_focus_on_selection()`**

Change (around line 7450):

```python
    def _auto_focus_on_selection(self, selected_shapes):
        """Auto-focus the selected shape's group_id if auto-focus is on."""
        if not self.auto_focus_instance:
            return
        if not selected_shapes:
            return
        current_shape = selected_shapes[0]
        if current_shape.group_id is None:
            return
        target_group_id = current_shape.group_id
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = shape.group_id != target_group_id
        self.canvas.update()
        self.status(
            self.tr("自动聚合: group_id={gid}").format(gid=target_group_id),
            2000,
        )
```

to:

```python
    def _auto_focus_on_selection(self, selected_shapes):
        """Auto-focus the selected shape's group_id if auto-focus is on."""
        if not self.auto_focus_instance:
            return
        if not selected_shapes:
            return

        current_shape = None
        for shape in selected_shapes:
            if (
                self.canvas.is_shape_interactive(shape)
                and shape.group_id is not None
            ):
                current_shape = shape
                break
        if current_shape is None:
            return

        target_group_id = current_shape.group_id
        self.auto_focus_group_id = target_group_id

        for shape in self.canvas.shapes:
            if shape.group_id != target_group_id:
                if getattr(shape, "selected", False):
                    shape.selected = False
                shape.hidden_by_filter = True
            else:
                shape.hidden_by_filter = False

        self.canvas.selected_shapes = [
            s
            for s in self.canvas.selected_shapes
            if getattr(s, "group_id", None) == target_group_id
        ]

        self.canvas.update()
        self._sync_label_list_hidden_by_filter()
        self.status(
            self.tr("自动聚合: group_id={gid}").format(gid=target_group_id),
            2000,
        )
```

- [ ] **Step 18: Replace `_escape_auto_focus_if_active()` and ESC handling**

Change `_escape_auto_focus_if_active()` (around line 7468) to:

```python
    def _escape_auto_focus_if_active(self):
        """Handle ESC in auto-focus mode: turn aggregation off."""
        if not self.auto_focus_instance:
            return False
        self.auto_focus_instance = False
        self.auto_focus_group_id = None
        self.show_all_instances()
        self.status(self.tr("已关闭自动聚合"), 2000)
        return True
```

`keyPressEvent()` (around line 7483) remains:

```python
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self._escape_auto_focus_if_active():
                event.accept()
                return
            event.accept()
            return
        super(LabelingWidget, self).keyPressEvent(event)
```

No change needed for `keyPressEvent()` if `_escape_auto_focus_if_active()` is already updated.

---

## Task 7: Tests

**Files:**
- Create: `tests/test_canvas_interaction.py`

- [ ] **Step 19: Add unit tests for the new Canvas gates**

Create `tests/test_canvas_interaction.py`:

```python
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtWidgets

    PYQT_AVAILABLE = True
except Exception:
    PYQT_AVAILABLE = False


class MockShape:
    def __init__(
        self,
        visible=True,
        hidden_by_filter=False,
        group_id=None,
        label="person",
        shape_type="rectangle",
    ):
        self.visible = visible
        self.hidden_by_filter = hidden_by_filter
        self.group_id = group_id
        self.label = label
        self.shape_type = shape_type


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt6 is required")
class TestCanvasInteraction(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance()
        if self.app is None:
            self.app = QtWidgets.QApplication([])
        from anylabeling.views.labeling.widgets.canvas import Canvas

        self.canvas = Canvas()
        self.canvas.show_labels = True

    def test_is_shape_interactive_when_visible(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.assertTrue(self.canvas.is_shape_interactive(shape))

    def test_is_shape_interactive_when_canvas_invisible(self):
        shape = MockShape()
        self.canvas.visible = {shape: False}
        self.assertFalse(self.canvas.is_shape_interactive(shape))

    def test_is_shape_interactive_when_shape_invisible(self):
        shape = MockShape(visible=False)
        self.canvas.visible = {shape: True}
        self.assertFalse(self.canvas.is_shape_interactive(shape))

    def test_is_shape_interactive_when_hidden_by_filter(self):
        shape = MockShape(hidden_by_filter=True)
        self.canvas.visible = {shape: True}
        self.assertFalse(self.canvas.is_shape_interactive(shape))

    def test_should_draw_standard_label_when_pose_view_off(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = False
        self.canvas.show_labels = True
        self.assertTrue(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_hides_when_pose_view_on(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = True
        self.canvas.show_labels = True
        self.assertFalse(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_hides_when_show_labels_off(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = False
        self.canvas.show_labels = False
        self.assertFalse(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_hides_when_not_interactive(self):
        shape = MockShape(hidden_by_filter=True)
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = False
        self.canvas.show_labels = True
        self.assertFalse(self.canvas._should_draw_standard_label(shape))
```

- [ ] **Step 20: Run new tests**

Run:

```bash
pytest tests/test_canvas_interaction.py -v
```

Expected: all 8 tests pass.

---

## Task 8: Verification

- [ ] **Step 21: Run full test suite**

Run:

```bash
pytest
```

Expected: existing tests plus new tests pass.

- [ ] **Step 22: Run formatter**

Run:

```bash
bash scripts/format_code.sh
```

Expected: black reformats touched files; no output means already compliant.

- [ ] **Step 23: Run linter**

Run:

```bash
flake8 anylabeling/views/labeling/widgets/canvas.py anylabeling/views/labeling/label_widget.py anylabeling/views/labeling/widgets/pose_label/pose_renderer.py tests/test_canvas_interaction.py
```

Expected: no errors (max complexity 18).

---

## Self-Review Checklist

- [ ] **Spec coverage:** Every requirement in `docs/0616_pose_view_label_hide_and_auto_aggregation_change_plan.md` maps to at least one task above.
- [ ] **Pose View native labels hidden:** Task 3 Step 8 (`_should_draw_standard_label`) and Step 9 (PoseRenderer outside `show_labels`).
- [ ] **`show_labels` controls Pose labels:** Task 4 Step 11.
- [ ] **Auto-focus ARMED/FOCUSED/OFF:** Task 6 Steps 15-18.
- [ ] **Invisible shapes not selectable:** Task 1 (`is_shape_interactive`) + Task 2 Steps 3-6.
- [ ] **Label list sync:** Task 5 Steps 12-14.
- [ ] **No placeholders:** Every step contains exact code or exact commands.
