"""
FlatIndex — lightweight in-memory index of shapes across all JSON files.

Design goals:
- Pure Python, no database dependency.
- Targets 500~1000 JSON files per batch (~30K shape records → ~22 MB).
- Supports incremental refresh on single-file update.
"""

import json
import logging
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FlattenedRecord:
    """A single shape, flattened for querying."""

    file_path: str  # absolute path to JSON
    image_path: str  # imagePath field from JSON
    shape_index: int  # index in shapes[]
    label: str
    shape_type: (
        str  # rectangle / polygon / point / linestrip / circle / rotation
    )
    group_id: Optional[int]
    flags: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    points_count: int = 0
    difficulty: bool = False

    # ---- computed / cached ----
    @property
    def filename(self) -> str:
        return osp.basename(self.file_path)


# ---------------------------------------------------------------------------
# FlatIndex
# ---------------------------------------------------------------------------


class FlatIndex:
    """
    In-memory index of all shapes across a set of JSON annotation files.

    Usage::

        index = FlatIndex()
        index.scan_files(list_of_json_paths, progress_callback=...)

        # query
        records = index.query(label="person", group_id=3)

        # full-table access
        for r in index.iter_all():
            ...
    """

    def __init__(self):
        self._records: List[FlattenedRecord] = []
        self._by_file: Dict[str, List[FlattenedRecord]] = (
            {}
        )  # file_path → records
        self._by_label: Dict[str, List[FlattenedRecord]] = (
            {}
        )  # label → records
        self._by_group: Dict[int, List[FlattenedRecord]] = (
            {}
        )  # group_id → records

        # metadata
        self._files_scanned: int = 0
        self._files_failed: List[Tuple[str, str]] = []  # (path, error)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def file_count(self) -> int:
        return len(self._by_file)

    @property
    def files_scanned(self) -> int:
        return self._files_scanned

    @property
    def files_failed(self) -> List[Tuple[str, str]]:
        return self._files_failed.copy()

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan_files(
        self,
        json_paths: List[str],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Scan a list of JSON files and build the index.

        Args:
            json_paths: List of absolute paths to JSON annotation files.
            progress_callback: Optional callable receiving current, total,
                and current_filename.
            cancel_check: Optional callable returning True when scanning should
                stop before the next file.
        """
        self.clear()
        total = len(json_paths)
        scanned = 0

        for idx, path in enumerate(json_paths, 1):
            if cancel_check and cancel_check():
                break
            try:
                self._scan_one(path)
            except Exception as exc:
                logger.warning(f"Failed to scan {path}: {exc}")
                self._files_failed.append((path, str(exc)))

            if progress_callback:
                progress_callback(idx, total, osp.basename(path))
            scanned = idx

        self._files_scanned = scanned
        logger.info(
            f"FlatIndex scan complete: {self.record_count} records "
            f"from {self.file_count}/{total} files "
            f"({len(self._files_failed)} failures)"
        )

    def _scan_one(self, file_path: str) -> None:
        """Parse one JSON file and index its shapes."""
        if not osp.isfile(file_path):
            raise FileNotFoundError(file_path)

        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        image_path = data.get("imagePath", "")
        shapes = data.get("shapes", [])

        records: List[FlattenedRecord] = []
        for i, shape in enumerate(shapes):
            rec = FlattenedRecord(
                file_path=file_path,
                image_path=image_path,
                shape_index=i,
                label=shape.get("label", ""),
                shape_type=shape.get("shape_type", ""),
                group_id=shape.get("group_id"),
                flags=shape.get("flags", {}) or {},
                attributes=shape.get("attributes", {}) or {},
                description=shape.get("description", "") or "",
                points_count=len(shape.get("points", []) or []),
                difficulty=bool(
                    shape.get("difficult", False)
                    or shape.get("flags", {}).get("difficult", False)
                ),
            )
            records.append(rec)

        self._by_file[file_path] = records
        for rec in records:
            self._records.append(rec)
            self._by_label.setdefault(rec.label, []).append(rec)
            if rec.group_id is not None:
                self._by_group.setdefault(rec.group_id, []).append(rec)

    def refresh_file(self, file_path: str) -> List[FlattenedRecord]:
        """
        Re-scan a single file (used after user saves changes).
        Returns the new records for this file.
        """
        old_records = self._by_file.pop(file_path, [])
        for rec in old_records:
            self._records.remove(rec)
            if rec.label in self._by_label:
                label_list = self._by_label[rec.label]
                label_list.remove(rec)
                if not label_list:
                    del self._by_label[rec.label]
            if rec.group_id is not None and rec.group_id in self._by_group:
                group_list = self._by_group[rec.group_id]
                group_list.remove(rec)
                if not group_list:
                    del self._by_group[rec.group_id]

        # re-scan
        self._scan_one(file_path)
        return self._by_file.get(file_path, [])

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        label: Optional[str] = None,
        shape_type: Optional[str] = None,
        group_id: Optional[int] = None,
        file_path: Optional[str] = None,
    ) -> List[FlattenedRecord]:
        """
        Return records matching ALL of the provided filters.
        Pass None for a filter to ignore it.
        """
        # start from the smallest candidate set
        if file_path is not None:
            candidates = self._by_file.get(file_path, [])
        elif group_id is not None:
            candidates = self._by_group.get(group_id, [])
        elif label is not None:
            candidates = self._by_label.get(label, [])
        else:
            candidates = self._records

        results = []
        for rec in candidates:
            if label is not None and rec.label != label:
                continue
            if shape_type is not None and rec.shape_type != shape_type:
                continue
            if group_id is not None and rec.group_id != group_id:
                continue
            if file_path is not None and rec.file_path != file_path:
                continue
            results.append(rec)
        return results

    def get_unique_labels(self) -> List[str]:
        """Return sorted list of all distinct labels in the index."""
        return sorted(self._by_label.keys())

    def get_unique_group_ids(self) -> List[int]:
        """Return sorted list of all distinct group_ids."""
        return sorted(self._by_group.keys())

    def get_files_containing_label(self, label: str) -> Set[str]:
        """Return set of file paths that contain at least one shape with the given label."""
        return {rec.file_path for rec in self._by_label.get(label, [])}

    def iter_all(self) -> Iterator[FlattenedRecord]:
        yield from self._records

    def iter_file(self, file_path: str) -> Iterator[FlattenedRecord]:
        yield from self._by_file.get(file_path, [])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self._records.clear()
        self._by_file.clear()
        self._by_label.clear()
        self._by_group.clear()
        self._files_failed.clear()
        self._files_scanned = 0
