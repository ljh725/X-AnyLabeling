"""Tests for staged dataset-index rebuilds."""

import json
from pathlib import Path

from anylabeling.views.labeling.dataset_index import (
    DatasetFilterIndex,
    install_staged_database,
)
from anylabeling.views.labeling.dataset_index.worker import (
    DatasetIndexWorker,
)


def _write_label(path: Path, label: str) -> None:
    """Write a minimal annotation JSON file."""
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


def test_progress_signal_is_throttled_but_first_and_last_are_kept():
    """Rapid per-file callbacks must not flood the UI event queue."""
    now = [0.0]
    progress = []
    worker = DatasetIndexWorker(
        "refresh",
        "cache.db",
        [],
        progress_interval_seconds=0.1,
        clock=lambda: now[0],
    )
    worker.progress_changed.connect(
        lambda current, total, filename: progress.append(
            (current, total, filename)
        )
    )

    worker._emit_progress(1, 100, "1.json")
    worker._emit_progress(2, 100, "2.json")
    now[0] = 0.11
    worker._emit_progress(3, 100, "3.json")
    worker._emit_progress(100, 100, "100.json")

    assert progress == [
        (1, 100, "1.json"),
        (3, 100, "3.json"),
        (100, 100, "100.json"),
    ]


def test_rebuild_worker_stages_before_replacing_live_database(tmp_path):
    """A completed rebuild must not mutate the live DB before installation."""
    image_path = tmp_path / "sample.jpg"
    json_path = tmp_path / "sample.json"
    db_path = tmp_path / "dataset.db"
    image_path.write_bytes(b"")
    _write_label(json_path, "new")

    live = DatasetFilterIndex(str(db_path), journal_mode="delete")
    live.open()
    live._conn.execute(
        "INSERT INTO dataset_meta (key, value) VALUES (?, ?)",
        ("marker", "old"),
    )
    live._conn.commit()
    live.close()

    completed = []
    worker = DatasetIndexWorker(
        "rebuild",
        str(db_path),
        [str(image_path)],
        dataset_root=str(tmp_path),
    )
    worker.finished.connect(completed.append)
    worker.run()

    assert len(completed) == 1
    result = completed[0]
    assert result.staged_db_path
    assert Path(result.staged_db_path).exists()

    unchanged = DatasetFilterIndex(str(db_path), journal_mode="delete")
    unchanged.open()
    assert unchanged.metadata()["marker"] == "old"
    unchanged.close()

    install_staged_database(result.staged_db_path, str(db_path))
    installed = DatasetFilterIndex(str(db_path))
    installed.open()
    assert installed.query_shapes(type("State", (), {})()) == {
        str(image_path): [0]
    }
    assert "marker" not in installed.metadata()
    installed.close()


def test_cancelled_rebuild_discards_stage_and_preserves_live_database(
    tmp_path,
):
    """Cancelling a rebuild must leave the previously installed DB intact."""
    image_path = tmp_path / "sample.jpg"
    json_path = tmp_path / "sample.json"
    db_path = tmp_path / "dataset.db"
    image_path.write_bytes(b"")
    _write_label(json_path, "person")

    live = DatasetFilterIndex(str(db_path), journal_mode="delete")
    live.open()
    live._conn.execute(
        "INSERT INTO dataset_meta (key, value) VALUES (?, ?)",
        ("marker", "keep"),
    )
    live._conn.commit()
    live.close()

    cancelled = []
    worker = DatasetIndexWorker(
        "rebuild",
        str(db_path),
        [str(image_path)],
        dataset_root=str(tmp_path),
    )
    worker.cancelled.connect(cancelled.append)
    worker.cancel()
    worker.run()

    assert len(cancelled) == 1
    assert list(tmp_path.glob("*.rebuild-*.tmp")) == []
    preserved = DatasetFilterIndex(str(db_path), journal_mode="delete")
    preserved.open()
    assert preserved.metadata()["marker"] == "keep"
    preserved.close()
