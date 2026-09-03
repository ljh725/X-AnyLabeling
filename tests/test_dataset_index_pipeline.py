"""Tests for bounded dataset-index rebuild pipelining."""

import threading

from anylabeling.views.labeling.dataset_index import (
    INDEX_STATUS_OK,
    DatasetFilterIndex,
)
from anylabeling.views.labeling.dataset_index.index import PreparedIndexFile


class PipelineProbeIndex(DatasetFilterIndex):
    """Coordinate readers and the writer to prove pipeline overlap."""

    def __init__(self) -> None:
        """Initialize an in-memory index and synchronization events."""
        super().__init__(":memory:")
        self.write_started = threading.Event()
        self.read_during_write = threading.Event()
        self.overlap_timed_out = False

    def _prepare_index_file(
        self,
        image_path: str,
        json_path: str,
        sort_order: int,
    ) -> PreparedIndexFile:
        """Return one result immediately and hold later reads for the writer."""
        if sort_order:
            if self.write_started.wait(timeout=1.0):
                self.read_during_write.set()
        return PreparedIndexFile(
            image_path=image_path,
            json_path=json_path,
            sort_order=sort_order,
            json_size=10,
            shapes=[
                (
                    "person",
                    "1",
                    "rectangle",
                    f"{sort_order:032x}",
                    0.0,
                    0.0,
                    10.0,
                    10.0,
                )
            ],
            status=INDEX_STATUS_OK,
            read_seconds=0.01,
        )

    def _insert_prepared_file(self, prepared: PreparedIndexFile) -> str:
        """Pause the first write until another reader observes it."""
        if prepared.sort_order == 0:
            self.write_started.set()
            if not self.read_during_write.wait(timeout=1.0):
                self.overlap_timed_out = True
        return super()._insert_prepared_file(prepared)


class FastProbeIndex(DatasetFilterIndex):
    """Prepare deterministic in-memory records without filesystem access."""

    def _prepare_index_file(
        self,
        image_path: str,
        json_path: str,
        sort_order: int,
    ) -> PreparedIndexFile:
        """Return one lightweight prepared record."""
        return PreparedIndexFile(
            image_path=image_path,
            json_path=json_path,
            sort_order=sort_order,
            status=INDEX_STATUS_OK,
            read_seconds=0.001,
        )


def test_reads_overlap_sqlite_writes_and_progress_stays_monotonic() -> None:
    """Completed reads must flow to SQLite without a 64-file barrier."""
    index = PipelineProbeIndex()
    assert index.open()
    image_files = [f"{number}.jpg" for number in range(4)]
    progress = []

    result = index._insert_files(
        image_files,
        progress_callback=lambda current, total, filename: progress.append(
            (current, total, filename)
        ),
    )

    assert not index.overlap_timed_out
    assert index.read_during_write.is_set()
    assert [current for current, _total, _name in progress] == [1, 2, 3, 4]
    assert index._all_image_paths() == image_files
    assert result.inserted == 4
    assert result.performance.max_in_flight == 4
    assert result.performance.json_bytes == 40
    assert result.performance.read_work_seconds == 0.04
    assert result.performance.sqlite_write_seconds >= 0.0
    index.close()


def test_prefetch_window_is_bounded_by_compatibility_limit() -> None:
    """The pipeline must not submit the complete dataset at once."""
    index = FastProbeIndex(":memory:")
    assert index.open()

    result = index._insert_files([f"{number}.jpg" for number in range(70)])

    assert result.inserted == 70
    assert result.performance.max_in_flight == 64
    index.close()


def test_pre_cancelled_rebuild_submits_no_reads_and_inserts_nothing() -> None:
    """Cancellation requested before rebuild must short-circuit the pipeline."""
    index = FastProbeIndex(":memory:")
    assert index.open()

    result = index._insert_files(
        ["a.jpg", "b.jpg"],
        cancel_check=lambda: True,
    )

    assert result.cancelled
    assert result.performance.max_in_flight == 0
    assert index._all_image_paths() == []
    index.close()
