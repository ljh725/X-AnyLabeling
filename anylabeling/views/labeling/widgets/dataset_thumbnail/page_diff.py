"""Pure identity and content comparison for bounded thumbnail pages."""

import os.path as osp
from dataclasses import dataclass
from typing import Iterable

from ...dataset_index.types import DatasetThumbnailRef


def identity(ref: DatasetThumbnailRef) -> tuple[str, str]:
    """Return an object's identity inside its owning dataset."""
    return osp.normcase(osp.abspath(ref.image_path)), ref.shape_id


@dataclass(frozen=True)
class PageDifference:
    """Describe independent membership, metadata and image changes."""

    added: frozenset
    removed: frozenset
    changed: frozenset
    images: frozenset
    moved: frozenset


def compare_pages(
    old: Iterable[DatasetThumbnailRef], new: Iterable[DatasetThumbnailRef]
) -> PageDifference:
    """Compare stable identities without treating array positions as IDs."""
    old = tuple(old)
    new = tuple(new)
    before = {identity(ref): ref for ref in old}
    after = {identity(ref): ref for ref in new}
    if len(before) != len(old) or len(after) != len(new):
        raise ValueError(
            "Duplicate object identities prevent incremental synchronization"
        )
    shared = before.keys() & after.keys()
    positions = {identity(ref): row for row, ref in enumerate(old)}
    return PageDifference(
        frozenset(after.keys() - before.keys()),
        frozenset(before.keys() - after.keys()),
        frozenset(key for key in shared if before[key] != after[key]),
        frozenset(
            key for key in shared if before[key].bbox != after[key].bbox
        ),
        frozenset(
            identity(ref)
            for row, ref in enumerate(new)
            if identity(ref) in shared and positions[identity(ref)] != row
        ),
    )
