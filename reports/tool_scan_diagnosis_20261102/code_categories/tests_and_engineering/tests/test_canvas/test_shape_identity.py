"""Persistent Shape identity tests for the 4.2.1 migration."""

import json
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling import label_file
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.shape_identity import (
    MISSING_SHAPE_ID,
    SHAPE_ID_FIELD,
    normalize_shape_identities,
    validate_shape_identities,
)
from anylabeling.views.labeling.widgets.canvas import Canvas


def make_shape(label="object", shape_id=None):
    """Build a small closed polygon, optionally with a fixed identity."""
    shape = Shape(label=label, shape_type="polygon", shape_id=shape_id)
    shape.points = [
        QtCore.QPointF(10.0, 10.0),
        QtCore.QPointF(30.0, 10.0),
        QtCore.QPointF(30.0, 30.0),
        QtCore.QPointF(10.0, 30.0),
    ]
    shape.close()
    return shape


def shape_payload(label="object", shape_id=MISSING_SHAPE_ID):
    """Build serialized Shape data, omitting the identity when requested."""
    payload = {
        "label": label,
        "score": None,
        "points": [[10.0, 10.0], [30.0, 10.0], [30.0, 30.0]],
        "group_id": None,
        "description": "",
        "difficult": False,
        "shape_type": "polygon",
        "flags": {},
        "attributes": {},
        "kie_linking": [],
    }
    if shape_id is not MISSING_SHAPE_ID:
        payload[SHAPE_ID_FIELD] = shape_id
    return payload


class TestShapeIdentityUnit(unittest.TestCase):
    def test_new_shape_gets_unique_hex_identity(self):
        first = Shape()
        second = Shape()
        self.assertIsInstance(first.xanylabeling_shape_id, str)
        self.assertEqual(len(first.xanylabeling_shape_id), 32)
        self.assertNotEqual(
            first.xanylabeling_shape_id, second.xanylabeling_shape_id
        )

    def test_serialization_writes_identity_and_load_preserves_it(self):
        shape = make_shape()
        data = shape.to_dict()

        self.assertEqual(next(iter(data)), SHAPE_ID_FIELD)
        self.assertEqual(
            data[SHAPE_ID_FIELD], shape.xanylabeling_shape_id
        )

        loaded = Shape().load_from_dict(data)
        self.assertEqual(
            loaded.xanylabeling_shape_id, shape.xanylabeling_shape_id
        )
        self.assertEqual(loaded.to_dict(), data)

    def test_identity_is_not_repeated_in_other_data(self):
        shape = make_shape()
        data = shape.to_dict()
        self.assertNotIn(SHAPE_ID_FIELD, shape.other_data)
        loaded = Shape().load_from_dict(data)
        self.assertNotIn(SHAPE_ID_FIELD, loaded.other_data)

    def test_load_without_preserving_identity_rotates_it(self):
        shape = make_shape()
        data = shape.to_dict()
        loaded = Shape().load_from_dict(data, preserve_shape_id=False)
        self.assertNotEqual(
            loaded.xanylabeling_shape_id, shape.xanylabeling_shape_id
        )
        self.assertEqual(len(loaded.xanylabeling_shape_id), 32)

    def test_legacy_payload_without_identity_gets_one(self):
        loaded = Shape().load_from_dict(shape_payload())
        self.assertEqual(len(loaded.xanylabeling_shape_id), 32)
        self.assertEqual(
            loaded.to_dict()[SHAPE_ID_FIELD],
            loaded.xanylabeling_shape_id,
        )

    def test_invalid_serialized_identity_is_replaced(self):
        for value in ("", None, 7, [], {}):
            with self.subTest(value=value):
                payload = shape_payload()
                payload[SHAPE_ID_FIELD] = value
                loaded = Shape().load_from_dict(payload)
                self.assertEqual(len(loaded.xanylabeling_shape_id), 32)

    def test_copy_keeps_identity_while_new_object_copy_rotates_it(self):
        shape = make_shape()
        cloned = shape.copy()
        self.assertEqual(
            cloned.xanylabeling_shape_id, shape.xanylabeling_shape_id
        )
        copied = shape.copy_for_new_object()
        self.assertNotEqual(
            copied.xanylabeling_shape_id, shape.xanylabeling_shape_id
        )
        self.assertEqual(copied.points, shape.points)


class TestShapeIdentityCollection(unittest.TestCase):
    def test_normalize_repairs_missing_invalid_and_duplicate(self):
        result = normalize_shape_identities(
            [MISSING_SHAPE_ID, "", "dup", "dup", "keep"]
        )
        self.assertEqual(len(result.identities), 5)
        self.assertEqual(len(set(result.identities)), 5)
        self.assertEqual(result.identities[4], "keep")
        self.assertEqual(
            [diagnostic.reason for diagnostic in result.diagnostics],
            ["missing", "invalid", "duplicate"],
        )
        self.assertEqual(result.diagnostics[2].first_index, 2)

    def test_normalize_respects_reserved_identities(self):
        result = normalize_shape_identities(
            ["taken", "taken"], reserved_ids=["taken"]
        )
        self.assertNotIn("taken", result.identities)
        self.assertEqual(len(set(result.identities)), 2)

    def test_validate_reports_only_violations(self):
        self.assertEqual(validate_shape_identities(["a", "b"]), ())
        diagnostics = validate_shape_identities(["a", "a", MISSING_SHAPE_ID])
        self.assertEqual(
            [diagnostic.reason for diagnostic in diagnostics],
            ["duplicate", "missing"],
        )


class TestLabelFileIdentity(unittest.TestCase):
    def _write_label_file(self, directory, shapes, image_name="image.png"):
        image_path = os.path.join(directory, image_name)
        Image.new("RGB", (40, 40), "white").save(image_path)
        label_path = os.path.join(directory, "image.json")
        with open(label_path, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "version": "test",
                    "flags": {},
                    "shapes": shapes,
                    "imagePath": image_name,
                    "imageData": None,
                },
                stream,
            )
        return label_path

    def test_load_repairs_duplicate_and_missing_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            label_path = self._write_label_file(
                directory,
                [
                    shape_payload("a", "same"),
                    shape_payload("b", "same"),
                    shape_payload("c"),
                ],
            )
            loaded = label_file.LabelFile(label_path)
            identities = [
                shape.xanylabeling_shape_id for shape in loaded.shapes
            ]
            self.assertEqual(len(set(identities)), 3)
            self.assertEqual(identities[0], "same")
            self.assertNotEqual(identities[1], "same")

    def test_save_rejects_duplicate_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(directory, "annotation.json")
            shapes = [
                make_shape("a", "same").to_dict(),
                make_shape("b", "same").to_dict(),
            ]
            with self.assertRaises(label_file.LabelFileError):
                label_file.LabelFile().save(
                    filename=filename,
                    shapes=shapes,
                    image_path="image.png",
                    image_height=10,
                    image_width=10,
                )
            self.assertFalse(os.path.exists(filename))

    def test_legacy_file_identity_becomes_stable_after_save(self):
        with tempfile.TemporaryDirectory() as directory:
            label_path = self._write_label_file(
                directory, [shape_payload("a"), shape_payload("b")]
            )
            loaded = label_file.LabelFile(label_path)
            first_ids = [
                shape.xanylabeling_shape_id for shape in loaded.shapes
            ]
            loaded.save(
                filename=label_path,
                shapes=[shape.to_dict() for shape in loaded.shapes],
                image_path="image.png",
                image_height=40,
                image_width=40,
            )
            reloaded = label_file.LabelFile(label_path)
            self.assertEqual(
                [shape.xanylabeling_shape_id for shape in reloaded.shapes],
                first_ids,
            )


class TestCanvasIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def setUp(self):
        self.canvas = Canvas(parent=None)
        self.canvas.pixmap = QtGui.QPixmap(100, 100)
        self.canvas.pixmap.fill(QtGui.QColor("black"))

    def tearDown(self):
        self.canvas.close()
        self.app.processEvents()

    def test_loading_against_existing_shapes_repairs_collisions(self):
        existing = make_shape("existing")
        self.canvas.load_shapes([existing])

        incoming = make_shape("incoming", existing.xanylabeling_shape_id)
        missing = make_shape("missing", None)
        self.canvas.load_shapes([incoming, missing], replace=False)

        identities = [
            shape.xanylabeling_shape_id for shape in self.canvas.shapes
        ]
        self.assertEqual(len(set(identities)), 3)
        self.assertEqual(self.canvas.shapes[0], existing)

    def test_replace_reuses_identity_of_reloaded_shapes(self):
        shape = make_shape()
        self.canvas.load_shapes([shape])
        self.canvas.load_shapes([shape])
        self.assertEqual(
            self.canvas.shapes[0].xanylabeling_shape_id,
            shape.xanylabeling_shape_id,
        )

    def test_pasted_shapes_get_new_identities(self):
        source = make_shape()
        pasted = self.canvas.prepare_pasted_shapes([source])
        self.assertEqual(len(pasted), 1)
        self.assertNotEqual(
            pasted[0].xanylabeling_shape_id,
            source.xanylabeling_shape_id,
        )
        self.assertEqual(pasted[0].points, source.points)

    def test_duplicated_shapes_get_new_identities(self):
        shape = make_shape()
        self.canvas.shapes = [shape]
        shape.selected = True
        self.canvas.selected_shapes = [shape]

        self.canvas.duplicate_selected_shapes()

        duplicated = self.canvas.shapes[-1]
        self.assertIsNot(duplicated, shape)
        self.assertNotEqual(
            duplicated.xanylabeling_shape_id,
            shape.xanylabeling_shape_id,
        )
        self.assertEqual(len(self.canvas.shapes), 2)

    def test_undo_restores_the_same_identity(self):
        shape = make_shape()
        self.canvas.load_shapes([shape])
        original_id = shape.xanylabeling_shape_id
        shape.points[0] = QtCore.QPointF(50.0, 50.0)
        self.canvas.store_shapes()

        self.canvas.restore_shape()

        self.assertEqual(len(self.canvas.shapes), 1)
        self.assertEqual(
            self.canvas.shapes[0].xanylabeling_shape_id, original_id
        )
