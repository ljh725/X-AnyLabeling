"""Incremental duplicate detection for edit-commit updates.

The tracker owns one incremental detector per file identity so an edit in
one image can never change another image's pairs, even when both images use
the same object ids.  A tracker result is only trusted when it still equals
the full scan of the same snapshot; otherwise the caller must recompute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from .duplicate import (
    DuplicatePair,
    DuplicateThresholds,
    IncrementalDuplicateDetector,
    PRESETS,
    RectangleSnapshot,
    full_scan,
    rectangle_snapshot_from_points,
    thresholds_from_mapping,
)
from .models import FileSnapshot, InspectionProfile

DUPLICATE_RULE_IDS = ("duplicate_boxes", "legacy_same_group_duplicate")


def thresholds_for_profile(
    profile: Optional[InspectionProfile],
) -> tuple[DuplicateThresholds, Mapping[str, object]]:
    """Resolve duplicate thresholds exactly like the duplicate rule does."""
    parameters: Mapping[str, object] = {}
    if profile is not None:
        rule = profile.rule_config("duplicate_boxes")
        if rule is not None and isinstance(rule.parameters, Mapping):
            parameters = rule.parameters
    preset = str(parameters.get("preset", "medium"))
    if preset not in PRESETS:
        preset = "medium"
    advanced = parameters.get("thresholds")
    if isinstance(advanced, Mapping) and advanced:
        resolved = thresholds_from_mapping(advanced)
        return resolved, {"preset": preset, **resolved.to_dict()}
    resolved = PRESETS[preset]
    return resolved, {"preset": preset, **resolved.to_dict()}


def rectangles_from_file(
    file: FileSnapshot,
) -> tuple[list[RectangleSnapshot], list[str]]:
    """Build validated rectangles, collecting invalid object ids."""
    rectangles: list[RectangleSnapshot] = []
    invalid: list[str] = []
    for shape in file.shapes:
        if shape.shape_type != "rectangle":
            continue
        if not shape.input_valid:
            invalid.append(shape.shape_id)
            continue
        try:
            rectangles.append(
                rectangle_snapshot_from_points(
                    shape.shape_id,
                    shape.label,
                    shape.points,
                    shape.group_id,
                )
            )
        except (TypeError, ValueError):
            invalid.append(shape.shape_id)
    return rectangles, invalid


def pair_key(pair: DuplicatePair) -> tuple[str, str]:
    return pair.key


@dataclass
class FilePairs:
    """One file's current pairs plus the tracker's consistency evidence."""

    relative_path: str
    pairs: tuple[DuplicatePair, ...] = ()
    invalid_ids: tuple[str, ...] = ()
    consistent: bool = True
    incremental_applied: bool = False
    truncated: bool = False


@dataclass
class DuplicateTracker:
    """Per-file incremental duplicate state, isolated by full identity."""

    thresholds: DuplicateThresholds
    detectors: dict[str, IncrementalDuplicateDetector] = field(
        default_factory=dict
    )
    last_pairs: dict[str, tuple[DuplicatePair, ...]] = field(
        default_factory=dict
    )
    invalid_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __init__(
        self,
        thresholds: Optional[DuplicateThresholds] = None,
        max_pairs: int = 5000,
    ) -> None:
        self.thresholds = (thresholds or PRESETS["medium"]).validate()
        self.max_pairs = max(1, int(max_pairs))
        self.detectors = {}
        self.last_pairs = {}
        self.invalid_ids = {}

    def set_thresholds(self, thresholds: DuplicateThresholds) -> Sequence[str]:
        """Apply new thresholds; every known file is rescanned completely."""
        self.thresholds = thresholds.validate()
        touched = []
        for key, detector in list(self.detectors.items()):
            rectangles = list(detector.rectangles.values())
            result = full_scan(
                rectangles, self.thresholds, max_pairs=self.max_pairs
            )
            detector.thresholds = self.thresholds
            detector.replace(result, rectangles)
            self.last_pairs[key] = result.pairs
            touched.append(key)
        return tuple(touched)

    def _detector(self, key: str) -> IncrementalDuplicateDetector:
        detector = self.detectors.get(key)
        if detector is None:
            detector = IncrementalDuplicateDetector(
                self.thresholds, self.max_pairs
            )
            self.detectors[key] = detector
        return detector

    def load_file(self, key: str, file: FileSnapshot) -> FilePairs:
        """Full scan one file and make it the baseline for later edits."""
        rectangles, invalid = rectangles_from_file(file)
        result = full_scan(
            rectangles, self.thresholds, max_pairs=self.max_pairs
        )
        detector = self._detector(key)
        detector.thresholds = self.thresholds
        detector.replace(result, rectangles)
        self.last_pairs[key] = result.pairs
        self.invalid_ids[key] = tuple(invalid)
        return FilePairs(
            relative_path=key,
            pairs=result.pairs,
            invalid_ids=tuple(invalid),
            consistent=not result.cancelled,
            incremental_applied=False,
            truncated=result.truncated,
        )

    def apply_edit(
        self,
        key: str,
        *,
        added: Iterable[RectangleSnapshot] = (),
        removed: Iterable[str] = (),
        updated: Iterable[RectangleSnapshot] = (),
        verify: bool = True,
    ) -> FilePairs:
        """Apply one edit incrementally and verify it equals a full scan."""
        detector = self._detector(key)
        detector.thresholds = self.thresholds
        for shape_id in removed:
            detector.remove(str(shape_id))
        for item in updated:
            detector.update_geometry(item)
        detector.update_many(added)
        rectangles = list(detector.rectangles.values())
        pairs = tuple(
            sorted(detector.pairs.values(), key=lambda pair: pair.key)
        )
        consistent = True
        if verify or detector.truncated:
            result = full_scan(
                rectangles, self.thresholds, max_pairs=self.max_pairs
            )
            consistent = self._same_pairs(pairs, result.pairs)
            if not consistent or result.truncated:
                detector.replace(result, rectangles)
            pairs = result.pairs
        self.last_pairs[key] = pairs
        return FilePairs(
            relative_path=key,
            pairs=pairs,
            invalid_ids=self.invalid_ids.get(key, ()),
            consistent=consistent,
            incremental_applied=True,
            truncated=detector.truncated,
        )

    def synchronize_file(
        self, key: str, file: FileSnapshot, *, verify: bool = False
    ) -> FilePairs:
        """Diff an edit-commit snapshot, removing deleted/non-rectangle objects.

        Reevaluate only changed rectangles. Full-scan comparison is explicit
        for validation, rather than an unconditional quadratic GUI cost.
        """
        detector = self.detectors.get(key)
        if detector is None:
            return self.load_file(key, file)
        if detector.truncated:
            return self.load_file(key, file)
        rectangles, invalid = rectangles_from_file(file)
        current = {item.shape_id: item for item in rectangles}
        previous = detector.rectangles
        self.invalid_ids[key] = tuple(invalid)
        return self.apply_edit(
            key,
            removed=set(previous).difference(current),
            added=(
                item for sid, item in current.items() if sid not in previous
            ),
            updated=(
                item
                for sid, item in current.items()
                if sid in previous and item != previous[sid]
            ),
            verify=verify,
        )

    def recheck_file(self, key: str, file: FileSnapshot) -> FilePairs:
        """Compare the stored state with the file's current snapshot."""
        rectangles, invalid = rectangles_from_file(file)
        detector = self.detectors.get(key)
        if detector is None:
            return self.load_file(key, file)
        result = full_scan(rectangles, self.thresholds)
        stored = tuple(sorted(detector.pairs.values(), key=lambda p: p.key))
        consistent = self._same_pairs(stored, result.pairs)
        self.invalid_ids[key] = tuple(invalid)
        return FilePairs(
            relative_path=key,
            pairs=result.pairs,
            invalid_ids=tuple(invalid),
            consistent=consistent,
            incremental_applied=False,
        )

    def file_state(self, key: str) -> Optional[FilePairs]:
        if key not in self.last_pairs:
            return None
        return FilePairs(
            relative_path=key,
            pairs=self.last_pairs[key],
            invalid_ids=self.invalid_ids.get(key, ()),
            truncated=self.detectors[key].truncated,
        )

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.detectors))

    def clear(self) -> None:
        self.detectors.clear()
        self.last_pairs.clear()
        self.invalid_ids.clear()

    @staticmethod
    def _same_pairs(
        first: Iterable[DuplicatePair], second: Iterable[DuplicatePair]
    ) -> bool:
        left = sorted((pair.key, pair.severity.value) for pair in first)
        right = sorted((pair.key, pair.severity.value) for pair in second)
        return left == right


def tracker_from_profile(
    profile: Optional[InspectionProfile],
) -> DuplicateTracker:
    thresholds, _ = thresholds_for_profile(profile)
    rule = profile.rule_config("duplicate_boxes") if profile else None
    limit = int(rule.parameters.get("max_pairs", 5000)) if rule else 5000
    return DuplicateTracker(thresholds, max_pairs=limit)
