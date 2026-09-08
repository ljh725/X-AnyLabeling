"""Persistent manual review decisions, independent of disposable indexes."""

import os.path as osp
import sqlite3
import uuid
from typing import Iterable

from ...dataset_index.types import DatasetThumbnailRef
from ...dataset_index.thumbnail_query import REVIEW_STATES


class ReviewStore:
    """Own the write connection for one dataset's explicit review states."""

    def __init__(self, path: str | None = None) -> None:
        """Use a shared in-memory database when no persistence is requested."""
        self.path = (
            path
            or f"file:thumbnail-review-{uuid.uuid4().hex}?mode=memory&cache=shared"
        )
        self.connection = sqlite3.connect(self.path, uri=True, timeout=5)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS marks (image_path TEXT NOT NULL,shape_id TEXT NOT NULL,signature TEXT NOT NULL,state TEXT NOT NULL,PRIMARY KEY(image_path,shape_id))"
        )
        self.connection.commit()

    def set_status(
        self, refs: Iterable[DatasetThumbnailRef], status: str
    ) -> None:
        """Atomically mark only unique, revision-bearing object references."""
        refs = tuple(refs)
        if status not in REVIEW_STATES:
            raise ValueError("Unknown review state")
        if not refs or any(
            not r.shape_id or not r.signature or not r.unique_identity
            for r in refs
        ):
            raise ValueError(
                "Review requires unique, indexed object identities"
            )
        with self.connection:
            self.connection.executemany(
                "INSERT OR REPLACE INTO marks VALUES (?,?,?,?)",
                [
                    (
                        osp.normcase(osp.abspath(r.image_path)),
                        r.shape_id,
                        r.signature,
                        status,
                    )
                    for r in refs
                ],
            )

    def close(self) -> None:
        """Close the writer without deleting persisted review data."""
        self.connection.close()
