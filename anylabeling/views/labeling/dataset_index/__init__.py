"""Pure dataset-index cache and query contracts."""

from .index import (
    DATASET_INDEX_CACHED,
    DATASET_INDEX_FAILED,
    DATASET_INDEX_MISSING,
    DATASET_INDEX_READY,
    DATASET_INDEX_STALE,
    DATASET_INDEX_SYNCING,
    INDEX_STATUS_ERROR,
    INDEX_STATUS_MISSING,
    INDEX_STATUS_OK,
    DatasetFilterIndex,
    DatasetIndexResult,
    install_staged_database,
    make_db_path,
    make_staging_db_path,
    remove_database_files,
)
from .types import (
    DatasetIndexAutoRefreshPolicy,
    DatasetIndexContext,
    DatasetIndexQueryProtocol,
    DatasetIndexState,
)

__all__ = [
    "DATASET_INDEX_CACHED",
    "DATASET_INDEX_FAILED",
    "DATASET_INDEX_MISSING",
    "DATASET_INDEX_READY",
    "DATASET_INDEX_STALE",
    "DATASET_INDEX_SYNCING",
    "INDEX_STATUS_ERROR",
    "INDEX_STATUS_MISSING",
    "INDEX_STATUS_OK",
    "DatasetFilterIndex",
    "DatasetIndexAutoRefreshPolicy",
    "DatasetIndexContext",
    "DatasetIndexQueryProtocol",
    "DatasetIndexResult",
    "DatasetIndexState",
    "install_staged_database",
    "make_db_path",
    "make_staging_db_path",
    "remove_database_files",
]
