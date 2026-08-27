"""
Data structures for the L1/L2 quality checker.

Defines:
- ``QcShape`` / ``QcFile``  — read-only view over a parsed annotation JSON,
  preserving raw ``points`` (the existing ``FlattenedRecord`` only stores
  ``points_count``, so the geometry rules need their own loader).
- ``QcShapeLoader``        — scan JSON files into ``QcFile`` objects.
- ``MatchCandidate``       — one candidate match (face→head / head→person).
- ``PrimaryMetric``        — {name, value, direction} for sorting / replay.
- ``QualityIssue``         — one reported problem, report.json-shaped.
- ``QualityReport``        — aggregate of a run.

These structures are pure data (no Qt / no optional deps), so the whole
quality module stays importable without PyQt6.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shape / File views
# ---------------------------------------------------------------------------


@dataclass
class QcShape:
    """Read-only view of one shape, keeping raw points for geometry."""

    shape_index: int
    label: str
    shape_type: str
    points: List[Tuple[float, float]]
    group_id: Optional[int]
    shape_id: str = ""
    flags: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    difficult: bool = False

    @property
    def points_count(self) -> int:
        return len(self.points)


@dataclass
class QcFile:
    """Read-only view of one annotation JSON file."""

    file_path: str
    image_path: str
    image_width: int
    image_height: int
    shapes: List[QcShape] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return osp.basename(self.file_path)

    def iter_shapes(self) -> Iterator[QcShape]:
        yield from self.shapes

    def shapes_with_label(self, label: str) -> List[QcShape]:
        return [s for s in self.shapes if s.label == label]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class QcShapeLoader:
    """Load annotation JSON files into ``QcFile`` objects.

    Read-only: never writes back to disk.  Malformed files are recorded
    in ``files_failed`` instead of aborting the batch.
    """

    def __init__(self) -> None:
        self.files: List[QcFile] = []
        self.files_failed: List[Tuple[str, str]] = []

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_shapes(self) -> int:
        return sum(len(f.shapes) for f in self.files)

    def load(
        self,
        json_paths: List[str],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[QcFile]:
        """Load a batch of JSON files.

        Args:
            json_paths: absolute paths to annotation JSON files.
            progress_callback: optional (current, total, filename).

        Returns:
            list of successfully loaded ``QcFile`` objects.
        """
        total = len(json_paths)
        for idx, path in enumerate(json_paths, 1):
            try:
                qc_file = self._load_one(path)
                self.files.append(qc_file)
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as exc:
                logger.warning(f"Failed to load {path}: {exc}", exc_info=True)
                self.files_failed.append((path, str(exc)))
            if progress_callback:
                progress_callback(idx, total, osp.basename(path))
        logger.info(
            f"QcShapeLoader: loaded {self.file_count}/{total} files "
            f"({self.total_shapes} shapes, "
            f"{len(self.files_failed)} failures)"
        )
        return self.files

    def _load_one(self, file_path: str) -> QcFile:
        if not osp.isfile(file_path):
            raise FileNotFoundError(file_path)
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(
                f"JSON root must be a mapping, got {type(data).__name__}"
            )

        image_path = data.get("imagePath", "") or ""
        image_height = int(data.get("imageHeight", 0) or 0)
        image_width = int(data.get("imageWidth", 0) or 0)

        shapes_raw = data.get("shapes", []) or []
        shapes: List[QcShape] = []
        for i, shape in enumerate(shapes_raw):
            if not isinstance(shape, dict):
                continue
            shapes.append(self._parse_shape(i, shape))

        return QcFile(
            file_path=file_path,
            image_path=image_path,
            image_width=image_width,
            image_height=image_height,
            shapes=shapes,
        )

    @staticmethod
    def _parse_shape(index: int, shape: Dict[str, Any]) -> QcShape:
        points_raw = shape.get("points", []) or []
        points: List[Tuple[float, float]] = []
        for pt in points_raw:
            if (
                isinstance(pt, (list, tuple))
                and len(pt) >= 2
                and all(isinstance(c, (int, float)) for c in pt[:2])
            ):
                points.append((float(pt[0]), float(pt[1])))
        gid = shape.get("group_id")
        # bool is a subclass of int; treat True/False as invalid gid
        if isinstance(gid, bool):
            gid = None
        flags = shape.get("flags", {}) or {}
        if not isinstance(flags, dict):
            flags = {}
        attrs = shape.get("attributes", {}) or {}
        if not isinstance(attrs, dict):
            attrs = {}
        difficult = bool(shape.get("difficult", False)) or bool(
            flags.get("difficult", False)
        )
        return QcShape(
            shape_index=index,
            label=str(shape.get("label", "") or ""),
            shape_type=str(shape.get("shape_type", "") or ""),
            points=points,
            group_id=gid if isinstance(gid, int) else None,
            shape_id=(
                str(shape.get("xanylabeling_shape_id"))
                if isinstance(shape.get("xanylabeling_shape_id"), str)
                and shape.get("xanylabeling_shape_id")
                else ""
            ),
            flags=flags,
            attributes=attrs,
            description=str(shape.get("description", "") or ""),
            difficult=difficult,
        )


# ---------------------------------------------------------------------------
# Match candidate / metric / issue
# ---------------------------------------------------------------------------


@dataclass
class MatchCandidate:
    """One candidate match for a face/head looking for a target."""

    shape_index: int
    label: str
    score: float
    metrics: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shape_index": self.shape_index,
            "label": self.label,
            "score": round(float(self.score), 4),
            "metrics": {
                k: round(float(v), 4) for k, v in self.metrics.items()
            },
        }


@dataclass
class PrimaryMetric:
    """The single metric used for ranking / replay / threshold feedback."""

    name: str
    value: float
    direction: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": round(float(self.value), 4),
            "direction": self.direction,
        }


@dataclass
class QualityIssue:
    """One reported quality issue.

    The shape mirrors the report.json per-issue schema in the v0 spec
    (section 7).  ``run_id`` is stamped at write time; ``issue_id`` is
    derived from stable components so it survives re-runs.
    """

    rule_id: str
    rule_name: str
    severity: str  # error | warning | info
    file_path: str
    shape_index: int  # -1 for file-level issues
    message: str
    shape_id: str = ""
    primary_metric: Optional[PrimaryMetric] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    thresholds_hit: Dict[str, Any] = field(default_factory=dict)
    image_path: str = ""
    label: str = ""
    group_id: Optional[int] = None
    bbox: Optional[List[float]] = None
    match: Optional[Dict[str, Any]] = None
    candidates: List[MatchCandidate] = field(default_factory=list)
    # stamped at report write time
    run_id: str = ""
    review_status: str = "unreviewed"

    def issue_id(self) -> str:
        """Stable id: file + shape + rule + primary metric value.

        ``run_id`` intentionally stays out of this id. Full-dataset scans
        and single-file re-scans produce different run ids, but they still
        need to re-link the same human review decision.
        """
        metric_key = ""
        if self.primary_metric is not None:
            metric_key = (
                f"{self.primary_metric.name}:{self.primary_metric.value:.4f}"
            )
        shape_key = self.shape_id or f"index:{self.shape_index}"
        raw = f"{self.file_path}|{shape_key}|{self.rule_name}|{metric_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "issue_id": self.issue_id(),
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "file_path": self.file_path,
            "image_path": self.image_path,
            "shape_index": self.shape_index,
            "shape_id": self.shape_id,
            "label": self.label,
            "group_id": self.group_id,
            "bbox": self.bbox,
            "message": self.message,
            "primary_metric": (
                self.primary_metric.to_dict() if self.primary_metric else None
            ),
            "metrics": {
                k: round(float(v), 4)
                for k, v in self.metrics.items()
                if isinstance(v, (int, float))
            },
            "thresholds_hit": self.thresholds_hit,
            "match": self.match,
            "candidates": [c.to_dict() for c in self.candidates],
            "review": {"status": self.review_status},
        }
        return d


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class QualityReport:
    """Aggregate output of a quality run."""

    run_id: str
    created_at: str
    threshold_profile: str
    thresholds: Dict[str, Any]
    source: Dict[str, Any]
    issues: List[QualityIssue] = field(default_factory=list)
    total_files: int = 0
    total_shapes: int = 0

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")

    def issues_by_rule(self) -> Dict[str, List[QualityIssue]]:
        grouped: Dict[str, List[QualityIssue]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.rule_name, []).append(issue)
        return grouped

    def issues_by_severity(self) -> Dict[str, int]:
        return {
            "error": self.error_count,
            "warning": self.warning_count,
            "info": self.info_count,
        }
