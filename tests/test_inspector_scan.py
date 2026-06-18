"""
Regression tests for FlatIndex scanning (``scan_files`` / ``_scan_one``).

Existing inspector tests construct ``FlattenedRecord`` objects directly,
which bypasses the JSON-parsing code path. These tests exercise the
parser end-to-end with synthetic annotation files so that parser
regressions (e.g. the ``difficulty=bool(...).get(...)`` AttributeError
that silently dropped every file) are caught.

Run: pytest tests/test_inspector_scan.py -v
"""

import json
import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

import importlib.util

_INSPECTOR_DIR = osp.join(
    osp.dirname(osp.dirname(osp.abspath(__file__))),
    "anylabeling",
    "views",
    "labeling",
    "widgets",
    "inspector",
)

_spec = importlib.util.spec_from_file_location(
    "_inspector_scan.flat_index",
    osp.join(_INSPECTOR_DIR, "flat_index.py"),
)
_flat_index_mod = importlib.util.module_from_spec(_spec)
sys.modules["_inspector_scan.flat_index"] = _flat_index_mod
_spec.loader.exec_module(_flat_index_mod)
FlatIndex = _flat_index_mod.FlatIndex
FlattenedRecord = _flat_index_mod.FlattenedRecord


def _write_json(tmp_path, name, payload):
    """Write ``payload`` as JSON to ``tmp_path/name`` and return path."""
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _shape(label="person", shape_type="rectangle", **extra):
    """Build a minimal shape dict with optional extra fields."""
    shape = {
        "label": label,
        "shape_type": shape_type,
        "points": [[0, 0], [10, 10]],
    }
    shape.update(extra)
    return shape


class TestScanFilesHappyPath:
    """Smoke tests for ``scan_files`` with well-formed files."""

    def test_single_file_single_shape(self, tmp_path):
        """A trivial file should produce one record and one file entry."""
        path = _write_json(
            tmp_path,
            "a.json",
            {
                "imagePath": "a.jpg",
                "shapes": [_shape()],
            },
        )
        index = FlatIndex()
        index.scan_files([path])
        assert index.file_count == 1
        assert index.record_count == 1
        assert index.files_failed == []

    def test_multiple_files_aggregate_counts(self, tmp_path):
        """Counts across files should aggregate correctly."""
        paths = []
        for name in ("a.json", "b.json", "c.json"):
            paths.append(
                _write_json(
                    tmp_path,
                    name,
                    {
                        "imagePath": name.replace(".json", ".jpg"),
                        "shapes": [_shape(), _shape(label="head")],
                    },
                )
            )
        index = FlatIndex()
        index.scan_files(paths)
        assert index.file_count == 3
        assert index.record_count == 6
        assert index.files_failed == []


class TestScanFilesDifficulty:
    """Regression tests for the ``difficulty`` field parsing.

    The previous implementation::

        difficulty=bool(
            shape.get("difficult", False)
            or shape.get("flags") or {}
        ).get("difficult", False)

    parsed as ``(bool(...)).get("difficult", False)`` and ALWAYS raised
    ``AttributeError: 'bool' object has no attribute 'get'``, silently
    dropping every file (caught by ``scan_files``'s try/except).
    These tests pin the intended OR-of-both-sources semantics.
    """

    def test_difficulty_top_level_true(self, tmp_path):
        """Top-level ``difficult: true`` ⇒ difficulty True."""
        path = _write_json(
            tmp_path,
            "a.json",
            {
                "imagePath": "a.jpg",
                "shapes": [_shape(difficult=True)],
            },
        )
        index = FlatIndex()
        index.scan_files([path])
        assert index.record_count == 1
        rec = next(index.iter_all())
        assert rec.difficulty is True

    def test_difficulty_in_flags(self, tmp_path):
        """``flags: {difficult: true}`` ⇒ difficulty True."""
        path = _write_json(
            tmp_path,
            "a.json",
            {
                "imagePath": "a.jpg",
                "shapes": [
                    _shape(flags={"difficult": True}),
                ],
            },
        )
        index = FlatIndex()
        index.scan_files([path])
        assert index.record_count == 1
        rec = next(index.iter_all())
        assert rec.difficulty is True

    def test_difficulty_either_source_is_true(self, tmp_path):
        """OR semantics — either source truthy ⇒ True."""
        path = _write_json(
            tmp_path,
            "a.json",
            {
                "imagePath": "a.jpg",
                "shapes": [
                    _shape(difficult=True, flags={}),
                    _shape(difficult=False, flags={"difficult": True}),
                    _shape(difficult=False, flags={"difficult": False}),
                    _shape(),
                ],
            },
        )
        index = FlatIndex()
        index.scan_files([path])
        assert index.record_count == 4
        records = list(index.iter_all())
        assert records[0].difficulty is True
        assert records[1].difficulty is True
        assert records[2].difficulty is False
        assert records[3].difficulty is False

    def test_scan_does_not_swallow_difficulty_errors(self, tmp_path):
        """The buggy line used to crash silently for every file.

        After the fix, the parser must not raise on the ``difficulty``
        field for any combination of inputs. With the fix reverted,
        ``record_count`` would be 0 (file swallowed into
        ``files_failed``).
        """
        path = _write_json(
            tmp_path,
            "a.json",
            {
                "imagePath": "a.jpg",
                "shapes": [
                    _shape(difficult=True),
                    _shape(flags={"difficult": True}),
                    _shape(difficult=False, flags={}),
                    _shape(),
                ],
            },
        )
        index = FlatIndex()
        index.scan_files([path])
        assert index.files_failed == []
        assert index.record_count == 4
        assert index.file_count == 1


class TestScanFilesMalformed:
    """``scan_files`` should tolerate (but report) malformed files."""

    def test_missing_file_recorded_as_failure(self, tmp_path):
        """A missing path should not abort the whole scan."""
        missing = str(tmp_path / "does_not_exist.json")
        good = _write_json(
            tmp_path,
            "good.json",
            {"imagePath": "g.jpg", "shapes": [_shape()]},
        )
        index = FlatIndex()
        index.scan_files([missing, good])
        assert index.file_count == 1
        assert index.record_count == 1
        assert len(index.files_failed) == 1
        assert index.files_failed[0][0] == missing

    def test_invalid_json_recorded_as_failure(self, tmp_path):
        """A JSON parse error should be reported, not raised."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        good = _write_json(
            tmp_path,
            "good.json",
            {"imagePath": "g.jpg", "shapes": [_shape()]},
        )
        index = FlatIndex()
        index.scan_files([str(bad), good])
        assert index.file_count == 1
        assert index.record_count == 1
        assert len(index.files_failed) == 1


class TestScanProgressCallback:
    """``progress_callback`` fires for every file, success or failure."""

    def test_progress_fires_for_every_file(self, tmp_path):
        paths = []
        for i in range(5):
            paths.append(
                _write_json(
                    tmp_path,
                    f"f{i}.json",
                    {"imagePath": f"f{i}.jpg", "shapes": [_shape()]},
                )
            )
        seen = []

        def on_progress(current, total, filename):
            seen.append((current, total, filename))

        index = FlatIndex()
        index.scan_files(paths, progress_callback=on_progress)
        assert len(seen) == 5
        assert seen[0][0] == 1
        assert seen[-1][0] == 5
        assert seen[0][1] == 5
