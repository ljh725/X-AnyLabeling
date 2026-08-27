"""File-level regression tests for persistent Shape identities."""

import json
from pathlib import Path

import pytest

from anylabeling.views.labeling import utils as _labeling_utils  # noqa: F401
from anylabeling.views.labeling.label_file import LabelFile, LabelFileError


def _shape(shape_id=...):
    """Return one JSON-serializable polygon with an optional identity."""
    shape = {
        "label": "person",
        "score": None,
        "points": [[1.0, 2.0], [10.0, 2.0], [10.0, 20.0]],
        "group_id": None,
        "description": "",
        "difficult": False,
        "shape_type": "polygon",
        "flags": {},
        "attributes": {},
        "kie_linking": [],
    }
    if shape_id is not ...:
        shape["xanylabeling_shape_id"] = shape_id
    return shape


def _write_label(path: Path, shapes: list[dict]) -> None:
    """Write a minimal X-AnyLabeling JSON fixture."""
    path.write_text(
        json.dumps(
            {
                "version": "2.0.0",
                "flags": {},
                "shapes": shapes,
                "imagePath": "missing.jpg",
                "imageData": None,
                "imageHeight": 30,
                "imageWidth": 30,
            }
        ),
        encoding="utf-8",
    )


def _save_shapes(path: Path, shapes: list[dict]) -> None:
    """Save Shape dictionaries through the production LabelFile boundary."""
    LabelFile().save(
        filename=str(path),
        shapes=shapes,
        image_path="missing.jpg",
        image_height=30,
        image_width=30,
        image_data=None,
        other_data={},
        flags={},
    )


def test_load_normalizes_legacy_invalid_and_duplicate_identities(tmp_path):
    """Load preserves the first valid ID and repairs every ambiguous Shape."""
    path = tmp_path / "sample.json"
    _write_label(
        path,
        [_shape(), _shape(None), _shape("kept"), _shape("kept")],
    )
    original_text = path.read_text(encoding="utf-8")

    label_file = LabelFile(str(path))

    identities = [shape.xanylabeling_shape_id for shape in label_file.shapes]
    assert len(set(identities)) == 4
    assert identities[2] == "kept"
    assert [item.reason for item in label_file.shape_identity_diagnostics] == [
        "missing",
        "invalid",
        "duplicate",
    ]
    assert path.read_text(encoding="utf-8") == original_text


def test_real_edit_save_and_reload_persists_normalized_identity(tmp_path):
    """A later real edit persists a legacy Shape's lazily assigned identity."""
    source = tmp_path / "legacy.json"
    target = tmp_path / "saved.json"
    _write_label(source, [_shape()])
    label_file = LabelFile(str(source))
    assigned_id = label_file.shapes[0].xanylabeling_shape_id
    label_file.shapes[0].label = "head"

    _save_shapes(target, [shape.to_dict() for shape in label_file.shapes])
    reloaded = LabelFile(str(target))

    assert reloaded.shapes[0].label == "head"
    assert reloaded.shapes[0].xanylabeling_shape_id == assigned_id
    assert reloaded.shape_identity_diagnostics == ()


def test_save_rejects_duplicate_ids_without_touching_target(tmp_path):
    """Preflight failure preserves the old file and creates no temp file."""
    target = tmp_path / "sample.json"
    original = '{"marker": "previous"}'
    target.write_text(original, encoding="utf-8")

    with pytest.raises(LabelFileError, match=r"shape\[1\].*shape\[0\]"):
        _save_shapes(target, [_shape("duplicate"), _shape("duplicate")])

    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("invalid_id", [None, "", 7])
def test_save_rejects_missing_or_invalid_identity(tmp_path, invalid_id):
    """Save requires every Shape dictionary to carry a valid identity."""
    target = tmp_path / "sample.json"
    shape = _shape() if invalid_id is None else _shape(invalid_id)

    with pytest.raises(LabelFileError, match="Invalid Shape identities"):
        _save_shapes(target, [shape])

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []
