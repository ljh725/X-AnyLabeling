"""Tests for the destructive rectangle cleanup script."""

import json
from pathlib import Path
from typing import Any, Dict

from scripts.remove_nested_duplicate_rectangles import clean_shapes, main


def _rectangle(
    label: str,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> Dict[str, Any]:
    """Build a minimal rectangle shape for a cleanup test."""
    return {
        "label": label,
        "shape_type": "rectangle",
        "points": [[left, top], [right, bottom]],
    }


def test_sample_nested_pairs_keep_the_smaller_rectangles() -> None:
    """The two observed frame-476 pairs should keep indexes 18 and 20."""
    shapes = [
        _rectangle("unused", index * 1000, 0, index * 1000 + 10, 10)
        for index in range(21)
    ]
    shapes[1] = _rectangle("listening", 216.85, 687.10, 412.02, 996.77)
    shapes[18] = _rectangle("listening", 215.76, 689.32, 398.57, 837.80)
    shapes[15] = _rectangle("listening", 1551.66, 632.38, 1715.23, 979.40)
    shapes[20] = _rectangle("listening", 1554.76, 632.32, 1715.39, 787.00)

    cleaned, removed, evidence = clean_shapes(shapes)

    assert removed == [1, 15]
    assert len(cleaned) == 19
    assert {item.kept_index for item in evidence} == {18, 20}
    assert {item.reason for item in evidence} == {"nested"}


def test_high_iou_equal_area_pair_keeps_earlier_entry() -> None:
    """A high-IoU tie should deterministically retain the first shape."""
    shapes = [
        _rectangle("listening", 0, 0, 100, 100),
        _rectangle("listening", 2.5, 0, 102.5, 100),
    ]

    cleaned, removed, evidence = clean_shapes(shapes)

    assert cleaned == [shapes[0]]
    assert removed == [1]
    assert evidence[0].reason == "iou"


def test_different_labels_are_compared_unless_restricted() -> None:
    """Mutually exclusive action labels should be cleaned by default."""
    shapes = [
        _rectangle("reading", 0, 0, 100, 100),
        _rectangle("listening", 10, 10, 90, 90),
    ]

    cleaned, removed, _evidence = clean_shapes(shapes)
    restricted, restricted_removed, _restricted_evidence = clean_shapes(
        shapes, same_label=True
    )

    assert cleaned == [shapes[1]]
    assert removed == [0]
    assert restricted == shapes
    assert restricted_removed == []


def test_nested_chain_keeps_only_the_smallest_rectangle() -> None:
    """Pairwise decisions should collapse a nested chain to its minimum."""
    shapes = [
        _rectangle("listening", 0, 0, 100, 100),
        _rectangle("listening", 10, 10, 90, 90),
        _rectangle("listening", 20, 20, 80, 80),
    ]

    cleaned, removed, _evidence = clean_shapes(shapes)

    assert cleaned == [shapes[2]]
    assert removed == [0, 1]


def test_non_rectangles_and_invalid_rectangles_are_preserved() -> None:
    """Only valid rectangle geometry should participate in deletion."""
    shapes = [
        {
            "label": "point",
            "shape_type": "point",
            "points": [[5, 5]],
        },
        _rectangle("invalid", 1, 1, 1, 5),
    ]

    cleaned, removed, evidence = clean_shapes(shapes)

    assert cleaned == shapes
    assert removed == []
    assert evidence == []


def test_cli_matches_images_and_writes_only_changed_jsons(
    tmp_path: Path,
) -> None:
    """Only changed JSONs selected by image filename should be generated."""
    images = tmp_path / "images"
    jsons = tmp_path / "jsons"
    output = tmp_path / "output"
    images.mkdir()
    jsons.mkdir()
    (images / "changed.jpg").write_bytes(b"image")
    (images / "unchanged.png").write_bytes(b"image")

    changed_shapes = [
        _rectangle("listening", 0, 0, 100, 100),
        _rectangle("listening", 10, 10, 90, 90),
    ]
    unchanged_shapes = [_rectangle("reading", 0, 0, 100, 100)]
    changed_path = jsons / "changed.json"
    unchanged_path = jsons / "unchanged.json"
    changed_path.write_text(
        json.dumps({"shapes": changed_shapes}), encoding="utf-8"
    )
    unchanged_path.write_text(
        json.dumps({"shapes": unchanged_shapes}), encoding="utf-8"
    )

    result = main(
        [
            "--images",
            str(images),
            "--jsons",
            str(jsons),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert len(json.loads(changed_path.read_text())["shapes"]) == 2
    assert (
        len(json.loads((output / "changed.json").read_text())["shapes"]) == 1
    )
    assert not (output / "unchanged.json").exists()


def test_cli_ignores_json_without_a_matching_image(tmp_path: Path) -> None:
    """A JSON absent from the image stem set must not be processed."""
    images = tmp_path / "images"
    jsons = tmp_path / "jsons"
    output = tmp_path / "output"
    images.mkdir()
    jsons.mkdir()
    (images / "selected.jpg").write_bytes(b"image")
    shapes = [
        _rectangle("listening", 0, 0, 100, 100),
        _rectangle("listening", 10, 10, 90, 90),
    ]
    (jsons / "not_selected.json").write_text(
        json.dumps({"shapes": shapes}), encoding="utf-8"
    )

    result = main(
        [
            "--images",
            str(images),
            "--jsons",
            str(jsons),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert not output.exists()


def test_cli_refuses_output_path_equal_to_source_file(
    tmp_path: Path,
) -> None:
    """Single-file mode must never rewrite the source JSON in place."""
    images = tmp_path / "images"
    images.mkdir()
    (images / "changed.jpg").write_bytes(b"image")
    source = tmp_path / "changed.json"
    original = json.dumps(
        {
            "shapes": [
                _rectangle("listening", 0, 0, 100, 100),
                _rectangle("listening", 10, 10, 90, 90),
            ]
        }
    )
    source.write_text(original, encoding="utf-8")

    result = main(
        [
            "--images",
            str(images),
            "--jsons",
            str(source),
            "--output",
            str(tmp_path),
            "--overwrite",
        ]
    )

    assert result == 1
    assert source.read_text(encoding="utf-8") == original


def test_cli_counts_non_utf8_json_as_failure_and_continues(
    tmp_path: Path,
) -> None:
    """A GBK-encoded JSON must fail loudly without aborting the batch."""
    images = tmp_path / "images"
    jsons = tmp_path / "jsons"
    output = tmp_path / "output"
    images.mkdir()
    jsons.mkdir()
    (images / "good.jpg").write_bytes(b"image")
    (images / "bad.jpg").write_bytes(b"image")
    (jsons / "good.json").write_text(
        json.dumps(
            {
                "shapes": [
                    _rectangle("listening", 0, 0, 100, 100),
                    _rectangle("listening", 10, 10, 90, 90),
                ]
            }
        ),
        encoding="utf-8",
    )
    (jsons / "bad.json").write_bytes(
        '{"shapes": [{"label": "中文"}]}'.encode("gbk")
    )

    result = main(
        [
            "--images",
            str(images),
            "--jsons",
            str(jsons),
            "--output",
            str(output),
        ]
    )

    assert result == 1
    assert (
        len(json.loads((output / "good.json").read_text())["shapes"]) == 1
    )


def test_cli_counts_non_dict_json_root_as_failure(tmp_path: Path) -> None:
    """A JSON whose root is not an object must fail without crashing."""
    images = tmp_path / "images"
    jsons = tmp_path / "jsons"
    output = tmp_path / "output"
    images.mkdir()
    jsons.mkdir()
    (images / "root.jpg").write_bytes(b"image")
    (jsons / "root.json").write_text("[1, 2]", encoding="utf-8")

    result = main(
        [
            "--images",
            str(images),
            "--jsons",
            str(jsons),
            "--output",
            str(output),
        ]
    )

    assert result == 1
    assert not (output / "root.json").exists()
