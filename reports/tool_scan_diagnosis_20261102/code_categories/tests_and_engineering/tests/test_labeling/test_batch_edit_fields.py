"""Field-scoped batch edit tests for the 4.2.1 migration."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling import editing_commands
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.widgets.label_dialog import LabelDialog


def make_shape(label, **fields):
    """Build a closed polygon with explicit metadata."""
    shape = Shape(label=label, shape_type="polygon")
    shape.points = [
        QtCore.QPointF(10.0, 10.0),
        QtCore.QPointF(30.0, 10.0),
        QtCore.QPointF(30.0, 30.0),
    ]
    shape.close()
    for key, value in fields.items():
        setattr(shape, key, value)
    return shape


class FakeCanvas:
    """Minimal canvas double that tracks undo backups."""

    def __init__(self, shapes):
        self.shapes = list(shapes)
        self.shapes_backups = []
        self.rectangle_size_invalidations = 0

    def store_shapes(self):
        self.shapes_backups.append([shape.copy() for shape in self.shapes])

    def invalidate_rectangle_size_issues(self):
        self.rectangle_size_invalidations += 1

    @property
    def is_shape_restorable(self):
        return len(self.shapes_backups) >= 2


def values(**overrides):
    base = {
        "label": "target",
        "flags": {},
        "group_id": None,
        "description": "",
        "difficult": False,
        "kie_linking": [],
        "review_status": "pending",
    }
    base.update(overrides)
    return base


class TestApplyFieldChanges(unittest.TestCase):
    def setUp(self):
        self.first = make_shape(
            "cat",
            group_id=1,
            description="first",
            flags={"reviewed": True},
            other_data={"review_status": "missed"},
        )
        self.second = make_shape(
            "dog",
            group_id=2,
            description="second",
            flags={"reviewed": False},
            other_data={"review_status": "pending"},
        )
        self.canvas = FakeCanvas([self.first, self.second])

    def test_only_touched_label_changes(self):
        changed = editing_commands.apply_field_changes(
            self.canvas,
            [self.first, self.second],
            values(label="bird", description="ignored"),
            {"label"},
        )

        self.assertEqual(changed, [self.first, self.second])
        self.assertEqual(self.first.label, "bird")
        self.assertEqual(self.second.label, "bird")
        self.assertEqual(self.first.group_id, 1)
        self.assertEqual(self.second.group_id, 2)
        self.assertEqual(self.first.description, "first")
        self.assertEqual(self.second.description, "second")
        self.assertEqual(self.first.flags, {"reviewed": True})
        self.assertEqual(self.second.flags, {"reviewed": False})
        self.assertEqual(
            self.first.other_data["review_status"], "missed"
        )

    def test_touched_description_keeps_other_fields(self):
        editing_commands.apply_field_changes(
            self.canvas,
            [self.first, self.second],
            values(description="shared note"),
            {"description"},
        )

        self.assertEqual(self.first.description, "shared note")
        self.assertEqual(self.second.description, "shared note")
        self.assertEqual(self.first.label, "cat")
        self.assertEqual(self.second.label, "dog")

    def test_untouched_patch_is_a_noop(self):
        changed = editing_commands.apply_field_changes(
            self.canvas,
            [self.first, self.second],
            values(label="other"),
            set(),
        )

        self.assertEqual(changed, [])
        self.assertEqual(self.first.label, "cat")
        self.assertEqual(self.second.label, "dog")

    def test_identical_value_is_not_recorded_as_change(self):
        changed = editing_commands.apply_field_changes(
            self.canvas,
            [self.first],
            values(label="cat"),
            {"label"},
        )

        self.assertEqual(changed, [])

    def test_explicit_value_matching_first_shape_still_applies(self):
        changed = editing_commands.apply_field_changes(
            self.canvas,
            [self.first, self.second],
            values(label="cat"),
            {"label"},
        )

        self.assertEqual(changed, [self.second])
        self.assertEqual(self.second.label, "cat")

    def test_review_status_only_written_when_touched(self):
        editing_commands.apply_field_changes(
            self.canvas,
            [self.second],
            values(review_status="false_positive"),
            {"review_status"},
        )

        self.assertEqual(
            self.second.other_data["review_status"], "false_positive"
        )
        self.assertEqual(
            self.first.other_data["review_status"], "missed"
        )

    def test_per_shape_label_resolver(self):
        changed = editing_commands.apply_field_changes(
            self.canvas,
            [self.first, self.second],
            values(label="new"),
            {"label"},
            label_resolver=lambda shape, label: f"{label}-{shape.label}",
        )

        self.assertEqual(len(changed), 2)
        self.assertEqual(self.first.label, "new-cat")
        self.assertEqual(self.second.label, "new-dog")

    def test_shapes_outside_canvas_are_ignored(self):
        outsider = make_shape("ghost")

        changed = editing_commands.apply_field_changes(
            self.canvas,
            [outsider],
            values(label="x"),
            {"label"},
        )

        self.assertEqual(changed, [])
        self.assertEqual(outsider.label, "ghost")

    def test_mutable_values_are_not_shared_between_shapes(self):
        editing_commands.apply_field_changes(
            self.canvas,
            [self.first, self.second],
            values(kie_linking=[[1, 2]]),
            {"kie_linking"},
        )

        self.assertEqual(self.first.kie_linking, [[1, 2]])
        self.assertIsNot(self.first.kie_linking, self.second.kie_linking)


class TestStoreUndoStep(unittest.TestCase):
    def test_first_edit_captures_baseline_then_result(self):
        canvas = FakeCanvas([make_shape("cat")])

        editing_commands.store_undo_step(canvas)

        self.assertEqual(len(canvas.shapes_backups), 2)

    def test_existing_baseline_only_adds_one_step(self):
        canvas = FakeCanvas([make_shape("cat")])
        canvas.store_shapes()

        editing_commands.store_undo_step(canvas)

        self.assertEqual(len(canvas.shapes_backups), 2)


class TestBatchEditWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def make_host(self, shapes, touched, result):
        host = SimpleNamespace(
            canvas=FakeCanvas(shapes),
            label_dialog=SimpleNamespace(
                pop_up=Mock(return_value=result),
                touched_fields=Mock(return_value=touched),
                get_review_status=Mock(return_value="pending"),
                add_label_history=Mock(),
            ),
            validate_label=Mock(return_value=True),
            error_message=Mock(),
            attributes={},
            label_list=SimpleNamespace(
                find_item_by_shape=Mock(return_value=None)
            ),
            unique_label_list=SimpleNamespace(
                find_items_by_label=Mock(return_value=True),
                create_item_from_label=Mock(),
                addItem=Mock(),
                set_item_label=Mock(),
            ),
            _update_shape_color=Mock(),
            _get_rgb_by_label=Mock(return_value=(0, 0, 0)),
            actions=SimpleNamespace(undo=Mock()),
            _config={"validate_label": None},
            set_dirty=Mock(),
            _refresh_shape_filters=Mock(),
            tr=lambda text: text,
        )
        host._resolve_label_attributes = (
            lambda shape, label: LabelingWidget._resolve_label_attributes(
                host, shape, label
            )
        )
        host._apply_field_patch = (
            lambda target, values, touched: LabelingWidget._apply_field_patch(
                host, target, values, touched
            )
        )
        return host

    def test_only_reported_fields_are_applied(self):
        shapes = [make_shape("cat", group_id=1), make_shape("dog")]
        result = ("bird", {}, 9, "note", True, [])
        host = self.make_host(shapes, {"label"}, result)

        changed = LabelingWidget.batch_edit_labels(host, shapes)

        self.assertTrue(changed)
        self.assertEqual([shape.label for shape in shapes], ["bird", "bird"])
        self.assertEqual([shape.group_id for shape in shapes], [1, None])
        self.assertFalse(shapes[0].difficult)
        self.assertEqual(len(host.canvas.shapes_backups), 2)
        host.actions.undo.setEnabled.assert_called_once_with(True)
        host.set_dirty.assert_called_once()
        host._refresh_shape_filters.assert_called_once()

    def test_cancelled_dialog_leaves_everything_untouched(self):
        shapes = [make_shape("cat")]
        host = self.make_host(
            shapes, set(), (None, None, None, None, False, [])
        )

        changed = LabelingWidget.batch_edit_labels(host, shapes)

        self.assertFalse(changed)
        self.assertEqual(shapes[0].label, "cat")
        self.assertEqual(host.canvas.shapes_backups, [])

    def test_invalid_label_aborts_without_mutation(self):
        shapes = [make_shape("cat")]
        host = self.make_host(
            shapes, {"label"}, ("bad label", {}, None, "", False, [])
        )
        host.validate_label = Mock(return_value=False)

        changed = LabelingWidget.batch_edit_labels(host, shapes)

        self.assertFalse(changed)
        self.assertEqual(shapes[0].label, "cat")
        host.error_message.assert_called_once()
        self.assertEqual(host.canvas.shapes_backups, [])

    def test_no_effective_change_skips_undo_and_dirty(self):
        shapes = [make_shape("cat")]
        host = self.make_host(
            shapes, {"label"}, ("cat", {}, None, "", False, [])
        )

        changed = LabelingWidget.batch_edit_labels(host, shapes)

        self.assertFalse(changed)
        self.assertEqual(host.canvas.shapes_backups, [])
        host.set_dirty.assert_not_called()


class TestBatchEditUndo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def test_single_undo_restores_previous_labels(self):
        canvas = Canvas(parent=None)
        shapes = [make_shape("cat"), make_shape("dog")]
        canvas.load_shapes(shapes)
        before = len(canvas.shapes_backups)

        editing_commands.apply_field_changes(
            canvas,
            canvas.shapes,
            values(label="bird"),
            {"label"},
        )
        editing_commands.store_undo_step(canvas)

        self.assertTrue(canvas.is_shape_restorable)
        canvas.restore_shape()

        self.assertEqual(
            [shape.label for shape in canvas.shapes], ["cat", "dog"]
        )
        # The widget reloads the restored shapes, which pushes the state
        # that makes the next undo possible again.
        canvas.load_shapes(canvas.shapes)
        self.assertEqual(len(canvas.shapes_backups), before)
        canvas.close()

    def test_label_attribute_resolution_preserves_exact_baseline(self) -> None:
        """Resolve attributes on a copy before recording the live baseline."""
        canvas = Canvas(parent=None)
        shape = make_shape("cat", attributes={"status": "custom"})
        canvas.load_shapes([shape])
        shape.description = "previous edit"

        def resolve_label(target: Shape, label: str) -> str:
            """Simulate the label-specific attribute default resolver."""
            target.attributes = {"status": "default"}
            return label

        editing_commands.apply_field_changes(
            canvas, [shape], values(label="dog"), {"label"}, resolve_label
        )
        editing_commands.store_undo_step(canvas)
        self.assertEqual(shape.attributes, {"status": "default"})
        canvas.restore_shape()
        self.assertEqual(canvas.shapes[0].label, "cat")
        self.assertEqual(canvas.shapes[0].attributes, {"status": "custom"})
        self.assertEqual(canvas.shapes[0].description, "previous edit")
        canvas.close()


class TestDialogTouchTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def setUp(self):
        self.dialog = LabelDialog()

    def tearDown(self):
        self.dialog.close()
        self.app.processEvents()

    def test_programmatic_fill_is_not_a_user_edit(self):
        self.dialog._loading_fields = True
        self.dialog.edit.setText("cat")
        self.dialog.edit_group_id.setText("3")
        self.dialog.edit_difficult.setChecked(True)
        self.dialog._loading_fields = False

        self.assertEqual(self.dialog.touched_fields(), frozenset())

    def test_user_edits_are_reported(self):
        self.dialog.edit.setText("cat")
        self.dialog.edit_group_id.setText("3")
        self.dialog.edit_description.setPlainText("note")
        self.dialog.edit_difficult.setChecked(True)

        self.assertEqual(
            self.dialog.touched_fields(),
            {"label", "group_id", "description", "difficult"},
        )

    def test_flag_toggle_and_review_click_are_reported(self):
        self.dialog._flags = {"cat": ["occluded"]}
        self.dialog._loading_fields = True
        self.dialog.reset_flags("cat")
        self.dialog._loading_fields = False

        checkbox = self.dialog.flags_layout.itemAt(0).widget()
        checkbox.setChecked(True)
        self.dialog.review_buttons["missed"].click()

        self.assertEqual(
            self.dialog.touched_fields(), {"flags", "review_status"}
        )

    @patch.object(LabelDialog, "exec", return_value=0)
    def test_pop_up_resets_state_and_clears_loading_flag(self, _exec):
        self.dialog._touched_fields.add("label")

        self.dialog.pop_up(
            text="cat",
            flags={},
            group_id=3,
            description="note",
            difficult=True,
            review_status="missed",
            move=False,
        )

        self.assertEqual(self.dialog.touched_fields(), frozenset())
        self.assertFalse(self.dialog._loading_fields)


if __name__ == "__main__":
    unittest.main()
