"""Filter result navigation engine.

Computes files / shapes that match a saved FilterState snapshot.
Used to build and update the "remaining matched files" navigation set.
"""

import json
import os.path as osp
from typing import Any, Dict, List, Optional

NAVIGATION_ENABLED = "enabled"
NAVIGATION_NO_ACTIVE_FILTER = "no_active_filter"
NAVIGATION_INDEX_NOT_READY = "index_not_ready"
NAVIGATION_NO_MATCHES = "no_matches"


class FilterNavigationSession:
    """Result of preparing dataset-wide filter navigation."""

    def __init__(
        self,
        status: str,
        matched_files: Optional[List[str]] = None,
        state: Optional[Any] = None,
    ):
        self.status = status
        self.matched_files = list(matched_files or [])
        self.state = state

    @property
    def active(self) -> bool:
        """Return whether the session has matched files to navigate."""
        return self.status == NAVIGATION_ENABLED and bool(self.matched_files)

    @property
    def initial_count(self) -> int:
        """Return the number of files captured when navigation starts."""
        return len(self.matched_files)


class FilterNavigationEngine:
    """Compute matched files and check whether a file / shapes still
    satisfy a FilterState snapshot.

    No Qt dependencies — stateless pure logic.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_matched_files(
        self,
        image_files: List[str],
        filter_state,
        output_dir: Optional[str] = None,
    ) -> List[str]:
        """Return image paths whose JSON contains at least one matching shape.

        The returned list preserves the order of *image_files*.
        """
        matched = []
        for image_file in image_files:
            if self.file_matches_filter(image_file, filter_state, output_dir):
                matched.append(image_file)
        return matched

    def prepare_dataset_navigation(
        self,
        image_files: List[str],
        filter_state,
        dataset_index,
    ) -> FilterNavigationSession:
        """Prepare a dataset-index-backed navigation session.

        UI callers provide current image order, active filter state, and the
        derived dataset index. The engine owns the match calculation and
        returns a status object for the UI to render.
        """
        if not filter_state.has_active_filter():
            return FilterNavigationSession(
                status=NAVIGATION_NO_ACTIVE_FILTER,
            )

        state = filter_state.copy()
        if dataset_index is None or not dataset_index.is_ready():
            return FilterNavigationSession(
                status=NAVIGATION_INDEX_NOT_READY,
                state=state,
            )

        all_matched = dataset_index.query(state)
        image_set = set(image_files)
        matched = [path for path in all_matched if path in image_set]
        if not matched:
            return FilterNavigationSession(
                status=NAVIGATION_NO_MATCHES,
                matched_files=[],
                state=state,
            )

        return FilterNavigationSession(
            status=NAVIGATION_ENABLED,
            matched_files=matched,
            state=state,
        )

    def file_matches_filter(
        self,
        image_file: str,
        filter_state,
        output_dir: Optional[str] = None,
    ) -> bool:
        """Return whether *image_file*'s JSON contains a matching shape."""
        label_file = self._label_file_for_image(image_file, output_dir)
        if not osp.exists(label_file):
            return False
        try:
            with open(label_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False
        for shape in data.get("shapes", []):
            if self._shape_matches_filter(shape, filter_state):
                return True
        return False

    def shapes_match_filter(self, shapes: List, filter_state) -> bool:
        """Return whether in-memory shapes contain at least one match."""
        for shape in shapes:
            if self._shape_matches_filter(shape, filter_state):
                return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _label_file_for_image(
        image_file: str, output_dir: Optional[str] = None
    ) -> str:
        label_file = osp.splitext(image_file)[0] + ".json"
        if output_dir:
            label_file = osp.join(output_dir, osp.basename(label_file))
        return label_file

    @staticmethod
    def _shape_value(shape, key: str, default=None):
        """Read *key* from either a dict or an object with attributes."""
        if isinstance(shape, dict):
            return shape.get(key, default)
        return getattr(shape, key, default)

    @classmethod
    def _shape_matches_filter(cls, shape, filter_state) -> bool:
        """Return True if *shape* satisfies all active conditions.

        - label set: OR within the set.
        - gid / shape_type: ANDed with labels.
        """
        label = cls._shape_value(shape, "label", "")
        gid = cls._shape_value(shape, "group_id", None)
        shape_type = cls._shape_value(shape, "shape_type", "")

        if filter_state.labels and label not in filter_state.labels:
            return False
        if filter_state.gid != "-1":
            if gid is None or str(gid) != str(filter_state.gid):
                return False
        if filter_state.shape_type:
            if shape_type != filter_state.shape_type:
                return False
        return True
