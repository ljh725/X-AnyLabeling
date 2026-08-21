"""Verify that the project-only shape identity stops at export boundaries."""

import json
import ast
from pathlib import Path

from tools.label_converter import RectLabelConverter


def _write_xlabel(path, image_name="sample.png"):
    """Write a representative X-AnyLabeling file with private metadata."""
    data = {
        "version": "2.0.0",
        "flags": {"document_flag": "keep"},
        "shapes": [
            {
                "label": "head",
                "points": [[10, 20], [40, 20], [40, 60], [10, 60]],
                "group_id": 7,
                "description": "keep this only in the source",
                "difficult": True,
                "shape_type": "rectangle",
                "flags": {"occluded": True},
                "attributes": {"state": "review"},
                "kie_linking": [["head", "person"]],
                "xanylabeling_shape_id": "shape-private-123",
            }
        ],
        "imagePath": image_name,
        "imageData": None,
        "imageHeight": 80,
        "imageWidth": 100,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def test_legacy_voc_and_yolo_converters_do_not_export_shape_id(tmp_path):
    """Legacy VOC and YOLO exports keep their existing public semantics."""
    label_path = tmp_path / "sample.json"
    original = _write_xlabel(label_path)

    converter = RectLabelConverter()
    converter.classes = ["head"]

    yolo_path = tmp_path / "sample.txt"
    converter.custom_to_yolov5(str(label_path), str(yolo_path))

    voc_path = tmp_path / "sample.xml"
    converter.custom_to_voc2017(str(label_path), str(voc_path))

    assert "shape-private-123" not in yolo_path.read_text(encoding="utf-8")
    assert "shape-private-123" not in voc_path.read_text(encoding="utf-8")

    source = json.loads(label_path.read_text(encoding="utf-8"))
    assert source == original
    assert source["shapes"][0]["group_id"] == 7
    assert source["shapes"][0]["flags"] == {"occluded": True}
    assert source["shapes"][0]["attributes"] == {"state": "review"}
    assert source["shapes"][0]["kie_linking"] == [["head", "person"]]


def test_active_coco_converter_has_no_private_shape_id_boundary_access():
    """The active COCO path serializes public fields only."""
    path = Path("anylabeling/views/labeling/label_converter.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    coco_source = ast.get_source_segment(
        path.read_text(encoding="utf-8"), methods["custom_to_coco"]
    )
    assert coco_source is not None
    assert "xanylabeling_shape_id" not in coco_source
    assert "group_id" in coco_source
    assert "difficult" in coco_source
