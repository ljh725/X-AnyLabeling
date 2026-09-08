"""Shared immutable types for the dataset-index lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence


class DatasetIndexState(str, Enum):
    """Runtime and persisted states of the derived dataset index."""

    MISSING = "missing"
    CACHED_UNVERIFIED = "cached_unverified"
    SYNCING = "syncing"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


class DatasetIndexAutoRefreshPolicy(str, Enum):
    """Explicit policy for verifying an attached persisted cache."""

    DISABLED = "disabled"
    ON_CACHE_ATTACH = "on_cache_attach"


class DatasetIndexQueryProtocol(Protocol):
    """Narrow read-only contract exposed to dataset-index consumers."""

    @property
    def is_query_ready(self) -> bool:
        """Return whether the current index connection can serve queries."""
        ...

    def query(self, filter_state: Any) -> List[str]:
        """Return image paths matching a filter-state snapshot."""
        ...

    def query_shapes(self, filter_state: Any) -> Dict[str, List[int]]:
        """Return matching shape indexes grouped by image path."""
        ...

    def query_label_counts(self) -> List[tuple[str, int]]:
        """Return non-empty labels and their indexed Shape counts."""
        ...

    def query_thumbnail_objects(
        self, label: str, limit: int = 100, offset: int = 0
    ) -> "DatasetThumbnailPage":
        """Return one bounded page of objects for an exact label."""
        ...

    def query_thumbnail_location(
        self, image_path: str, shape_id: str
    ) -> Optional["DatasetThumbnailLocation"]:
        """Return one object's stable position inside its label results."""
        ...


@dataclass(frozen=True)
class DatasetThumbnailRef:
    """Immutable lightweight reference used by the thumbnail browser."""

    image_path: str
    json_path: str
    sort_order: int
    shape_index: int
    shape_id: str
    label: str
    bbox: Optional[tuple[float, float, float, float]] = None
    score: Optional[float] = None
    description: str = ""
    difficult: bool = False
    group_id: str = "-1"
    shape_type: str = ""
    image_width: Optional[float] = None
    image_height: Optional[float] = None
    signature: str = ""
    review_status: str = "unreviewed"
    unique_identity: bool = True


@dataclass(frozen=True)
class DatasetThumbnailPage:
    """A bounded, stable page of indexed thumbnail references."""

    label: str
    total: int
    limit: int
    offset: int
    items: tuple[DatasetThumbnailRef, ...] = ()


@dataclass(frozen=True)
class DatasetThumbnailLocation:
    """Stable location of one uniquely indexed object within its label."""

    image_path: str
    json_path: str
    sort_order: int
    shape_index: int
    shape_id: str
    label: str
    offset: int


@dataclass(frozen=True)
class DatasetIndexContext:
    """Immutable identity and file snapshot for one dataset-index session."""

    dataset_root: Optional[str] = None
    output_dir: Optional[str] = None
    image_files: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        dataset_root: Optional[str],
        output_dir: Optional[str],
        image_files: Sequence[str],
    ) -> "DatasetIndexContext":
        """Create a context with an immutable image-file snapshot.

        Args:
            dataset_root: Normalized root that owns the cache.
            output_dir: Optional directory containing annotation JSON files.
            image_files: Complete dataset image list in navigation order.

        Returns:
            An immutable dataset-index context.
        """
        return cls(
            dataset_root=dataset_root,
            output_dir=output_dir,
            image_files=tuple(image_files),
        )


__all__ = [
    "DatasetIndexAutoRefreshPolicy",
    "DatasetIndexContext",
    "DatasetIndexQueryProtocol",
    "DatasetIndexState",
    "DatasetThumbnailLocation",
    "DatasetThumbnailPage",
    "DatasetThumbnailRef",
]
