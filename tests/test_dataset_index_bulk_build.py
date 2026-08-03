"""Tests for deferred dataset-index query-index construction."""

import json
from pathlib import Path
from typing import Set

from anylabeling.views.labeling.dataset_index.index import (
    QUERY_INDEX_DEFINITIONS,
    DatasetFilterIndex,
)


def _write_annotation(path: Path, label: str = "person") -> None:
    """Write one minimal annotation JSON file."""
    path.write_text(
        json.dumps(
            {
                "shapes": [
                    {
                        "label": label,
                        "group_id": 1,
                        "shape_type": "rectangle",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _query_index_names(index: DatasetFilterIndex) -> Set[str]:
    """Return explicitly named query indexes from the open database."""
    rows = index._conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_default_open_still_creates_all_query_indexes(tmp_path: Path) -> None:
    """Normal live indexes must retain the existing eager schema behavior."""
    index = DatasetFilterIndex(
        str(tmp_path / "live.db"),
        journal_mode="delete",
    )
    try:
        assert index.open()
        expected = {name for name, _statement in QUERY_INDEX_DEFINITIONS}
        assert _query_index_names(index) == expected
    finally:
        index.close()


def test_deferred_rebuild_creates_indexes_after_loading_rows(
    tmp_path: Path,
) -> None:
    """A completed staging rebuild must install every query index."""
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"")
    _write_annotation(tmp_path / "sample.json")
    index = DatasetFilterIndex(
        str(tmp_path / "staged.db"),
        journal_mode="delete",
        defer_query_indexes=True,
    )
    try:
        assert index.open()
        assert _query_index_names(index) == set()

        result = index.rebuild([str(image_path)])

        expected = {name for name, _statement in QUERY_INDEX_DEFINITIONS}
        assert not result.cancelled
        assert result.shape_count == 1
        assert result.performance.index_build_seconds > 0.0
        assert _query_index_names(index) == expected
        assert index.integrity_check()
        assert index.foreign_key_check()
        assert index.query_shapes(type("State", (), {})()) == {
            str(image_path): [0]
        }
    finally:
        index.close()


def test_cancellation_during_index_build_rolls_back_partial_indexes(
    tmp_path: Path,
) -> None:
    """Cancellation between index builds must leave no partial index set."""
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"")
    _write_annotation(tmp_path / "sample.json")
    index = DatasetFilterIndex(
        str(tmp_path / "cancelled-stage.db"),
        journal_mode="delete",
        defer_query_indexes=True,
    )
    pipeline_finished = False
    index_cancel_checks = 0

    def progress(current: int, total: int, _filename: str) -> None:
        """Record when the file-loading pipeline reaches its final item."""
        nonlocal pipeline_finished
        pipeline_finished = current == total

    def cancel_check() -> bool:
        """Cancel before the second deferred index is created."""
        nonlocal index_cancel_checks
        if not pipeline_finished:
            return False
        index_cancel_checks += 1
        return index_cancel_checks >= 2

    try:
        result = index.rebuild(
            [str(image_path)],
            progress_callback=progress,
            cancel_check=cancel_check,
        )

        assert result.cancelled
        assert result.performance.index_build_seconds == 0.0
        assert _query_index_names(index) == set()
    finally:
        index.close()
