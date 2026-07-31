"""Compatibility import for the relocated dataset-index worker."""

from .dataset_index.worker import (
    DEFAULT_PROGRESS_INTERVAL_SECONDS,
    DatasetIndexWorker,
)

__all__ = ["DEFAULT_PROGRESS_INTERVAL_SECONDS", "DatasetIndexWorker"]
