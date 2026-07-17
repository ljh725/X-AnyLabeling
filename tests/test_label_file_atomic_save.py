"""Regression tests for atomic JSON label persistence."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

# The application imports the shared labeling utilities before LabelFile.
# Mirror that order to avoid the package's existing visualization import cycle.
from anylabeling.views.labeling import utils as _labeling_utils  # noqa: F401
from anylabeling.views.labeling.label_file import LabelFile, LabelFileError


def _save_empty_label(path: Path) -> None:
    """Save a minimal valid label file."""
    LabelFile().save(
        filename=str(path),
        shapes=[],
        image_path="sample.jpg",
        image_height=10,
        image_width=10,
        image_data=None,
        other_data={},
        flags={},
    )


def test_label_file_save_atomically_replaces_target(tmp_path):
    """A successful save leaves a complete JSON document at the target."""
    target = tmp_path / "sample.json"

    _save_empty_label(target)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["imagePath"] == "sample.jpg"
    assert data["shapes"] == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_label_file_save_failure_preserves_previous_json(tmp_path):
    """A failed final replace must not truncate the previous JSON file."""
    target = tmp_path / "sample.json"
    original = '{"marker": "previous"}'
    target.write_text(original, encoding="utf-8")

    with mock.patch.object(
        os, "replace", side_effect=OSError("replace failed")
    ):
        with pytest.raises(LabelFileError):
            _save_empty_label(target)

    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.tmp")) == []
