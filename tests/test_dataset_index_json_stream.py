"""Tests for bounded-memory dataset-index JSON parsing."""

import io
import json

import pytest

from anylabeling.views.labeling.dataset_filter_index import (
    DatasetFilterIndex as LegacyDatasetFilterIndex,
)
from anylabeling.views.labeling.dataset_index import DatasetFilterIndex
from anylabeling.views.labeling.dataset_index.json_stream import (
    JsonStreamError,
    read_top_level_array,
)


class TrackingStream(io.StringIO):
    """Record requested chunk sizes for streaming assertions."""

    def __init__(self, value: str) -> None:
        """Initialize an in-memory stream and its read-size log."""
        super().__init__(value)
        self.read_sizes = []

    def read(self, size: int = -1) -> str:
        """Record and execute one bounded read."""
        self.read_sizes.append(size)
        return super().read(size)


def test_large_image_data_is_skipped_with_bounded_reads() -> None:
    """Large unrelated fields must never be requested in one full-file read."""
    document = json.dumps(
        {
            "imageData": "A" * (1024 * 1024),
            "shapes": [
                {
                    "label": "person",
                    "group_id": 7,
                    "shape_type": "rectangle",
                }
            ],
            "flags": {"reviewed": True},
        }
    )
    stream = TrackingStream(document)

    shapes = read_top_level_array(stream, "shapes", chunk_size=256)

    assert shapes[0]["label"] == "person"
    assert stream.read_sizes
    assert -1 not in stream.read_sizes
    assert max(stream.read_sizes) <= 256


def test_malformed_content_after_shapes_is_still_rejected() -> None:
    """Streaming must validate the complete document, not stop after shapes."""
    document = '{"shapes": [], "flags": [true,]}'

    with pytest.raises(JsonStreamError):
        read_top_level_array(io.StringIO(document), "shapes", chunk_size=256)


def test_index_extracts_only_query_fields_from_streamed_json(tmp_path) -> None:
    """The index must preserve label, gid, and shape-type query semantics."""
    json_path = tmp_path / "sample.json"
    json_path.write_text(
        json.dumps(
            {
                "imageData": "A" * 10000,
                "shapes": [
                    {
                        "label": "face",
                        "group_id": None,
                        "shape_type": "polygon",
                        "points": [[1, 2], [3, 4]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    shapes, error = DatasetFilterIndex._read_shapes(str(json_path))

    assert shapes == [("face", "-1", "polygon")]
    assert error == ""


def test_legacy_module_forwards_to_dataset_index_package() -> None:
    """Existing extensions may keep importing the pre-migration module path."""
    assert LegacyDatasetFilterIndex is DatasetFilterIndex
