"""Persistent manual review decisions, independent of disposable indexes."""

import os.path as osp
import sqlite3
import uuid
from typing import Iterable

from ...dataset_index.types import DatasetThumbnailRef
from ...dataset_index.thumbnail_query import REVIEW_STATES
from .history_store import HistoryStore


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
        self.history = HistoryStore(self.connection, self.path)

    def set_status(
        self,
        refs: Iterable[DatasetThumbnailRef],
        status: str,
        view: dict | None = None,
    ) -> dict:
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
        items = [
            dict(
                image_path=osp.normcase(osp.abspath(r.image_path)),
                json_path=r.json_path,
                shape_id=r.shape_id,
                before=r.review_status,
                after=status,
                signature=r.signature,
                label=r.label,
                status=(
                    "unchanged" if r.review_status == status else "succeeded"
                ),
            )
            for r in refs
        ]
        # A failed state write rolls back the history row in the same database.
        import uuid
        from datetime import datetime, timezone

        record = dict(
            id=uuid.uuid4().hex,
            created=datetime.now(timezone.utc).isoformat(),
            kind="review",
            state="completed",
            parent="",
            view=view or {},
            items=items,
            manifest_path="",
            transaction_id="",
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
            self.history.put(record)
        return record

    def revert(
        self, operation_id: str, selected: list[dict], refs: tuple
    ) -> dict:
        """Reverse review states atomically while retaining newer decisions."""
        from datetime import datetime, timezone

        current = {
            (osp.normcase(osp.abspath(r.image_path)), r.shape_id): r
            for r in refs
        }
        record = dict(
            id=uuid.uuid4().hex,
            created=datetime.now(timezone.utc).isoformat(),
            kind="review-revert",
            state="completed",
            parent=operation_id,
            view={},
            items=[],
            manifest_path="",
            transaction_id="",
        )
        with self.connection:
            for old in selected:
                item = dict(
                    old, before=old.get("after"), after=old.get("before")
                )
                ref = current.get((old["image_path"], old["shape_id"]))
                latest = self.connection.execute(
                    "SELECT h.id FROM thumbnail_history h,json_each(h.payload,'$.items') i "
                    "WHERE h.kind IN ('review','review-revert') AND "
                    "json_extract(i.value,'$.image_path')=? AND json_extract(i.value,'$.shape_id')=? "
                    "AND json_extract(i.value,'$.status')='succeeded' ORDER BY h.created DESC LIMIT 1",
                    (old["image_path"], old["shape_id"]),
                ).fetchone()
                valid = (
                    ref
                    and ref.unique_identity
                    and ref.signature == old.get("signature")
                    and ref.review_status == old.get("after")
                    and latest
                    and latest[0] == operation_id
                    and old.get("status") == "succeeded"
                    and not self.history.consumed(operation_id, old)
                )
                item["status"] = "succeeded" if valid else "conflict"
                item["message"] = (
                    "" if valid else "Review state or object changed"
                )
                if valid:
                    self.connection.execute(
                        "INSERT OR REPLACE INTO marks VALUES (?,?,?,?)",
                        (
                            old["image_path"],
                            old["shape_id"],
                            ref.signature,
                            old["before"],
                        ),
                    )
                    self.connection.execute(
                        "INSERT INTO thumbnail_consumed VALUES (?,?,?,?)",
                        (
                            operation_id,
                            old["image_path"],
                            old["shape_id"],
                            record["id"],
                        ),
                    )
                record["items"].append(item)
            if any(i["status"] == "conflict" for i in record["items"]):
                record["state"] = (
                    "partial"
                    if any(i["status"] == "succeeded" for i in record["items"])
                    else "failed"
                )
            self.history.put(record)
        return record

    def close(self) -> None:
        """Close the writer without deleting persisted review data."""
        self.connection.close()
