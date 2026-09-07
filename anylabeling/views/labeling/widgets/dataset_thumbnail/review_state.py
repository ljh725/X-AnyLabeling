"""Dataset-scoped display preferences and independent review bookmarks."""

from __future__ import annotations

import hashlib
import json
import os.path as osp
from dataclasses import asdict, dataclass

from PyQt6 import QtCore

from ...dataset_index import DatasetThumbnailRef


@dataclass(frozen=True)
class ReviewPosition:
    """Keep the recorded label and stable object identity for human review."""

    image_path: str
    label: str
    shape_id: str
    shape_index: int

    @classmethod
    def from_ref(cls, ref: DatasetThumbnailRef) -> ReviewPosition:
        """Capture a reference without reading or modifying annotation data."""
        return cls(ref.image_path, ref.label, ref.shape_id, ref.shape_index)

    @classmethod
    def parse(cls, value: object) -> ReviewPosition | None:
        """Ignore malformed saved records rather than inventing a target."""
        if not isinstance(value, dict):
            return None
        fields = ("image_path", "label", "shape_id")
        if not all(isinstance(value.get(key), str) for key in fields):
            return None
        if not value["image_path"] or not value["label"]:
            return None
        index = value.get("shape_index")
        if type(index) is not int or index < 0:
            return None
        return cls(*(value[key] for key in fields), index)


class ThumbnailReviewState:
    """Persist one dataset's state in a single versioned settings value."""

    def __init__(
        self, dataset_root: str, settings: QtCore.QSettings | None = None
    ) -> None:
        """Load validated bookmarks; omitted settings gives isolated state."""
        self.root = osp.normcase(osp.abspath(dataset_root))
        token = hashlib.sha256(self.root.encode("utf-8")).hexdigest()
        self.key = f"thumbnail_review/{token}/state"
        self.settings = settings
        self.card_width = 220
        self.page_end = None
        self.last_click = None
        if settings is not None:
            self._load(settings.value(self.key, ""))

    def _load(self, raw: object) -> None:
        """Read only the supported schema and bounded display preference."""
        try:
            value = json.loads(raw) if isinstance(raw, str) else None
        except (ValueError, TypeError):
            return
        if not isinstance(value, dict) or value.get("version") != 1:
            return
        width = value.get("card_width")
        if type(width) is int:
            self.card_width = max(160, min(520, width))
        self.page_end = ReviewPosition.parse(value.get("page_end"))
        self.last_click = ReviewPosition.parse(value.get("last_click"))

    def save(self) -> bool:
        """Flush to disk before window destruction and report failures."""
        if self.settings is None:
            return True
        value = dict(
            version=1,
            card_width=self.card_width,
            page_end=asdict(self.page_end) if self.page_end else None,
            last_click=asdict(self.last_click) if self.last_click else None,
        )
        self.settings.setValue(self.key, json.dumps(value, ensure_ascii=False))
        self.settings.sync()
        return self.settings.status() == QtCore.QSettings.Status.NoError

    def describe(
        self, position: ReviewPosition | None, object_id: bool
    ) -> str:
        """Display relative image paths and an unambiguous object ID."""

        def tr(text: str) -> str:
            """Translate the persisted-position display without UI coupling."""
            return QtCore.QCoreApplication.translate(
                "ThumbnailReviewState", text
            )

        if position is None:
            return tr("No record")
        try:
            path = osp.relpath(position.image_path, self.root)
        except ValueError:
            path = position.image_path
        result = f"{path} · {position.label}"
        if object_id:
            result += (
                tr(" · object #%1 · ID: %2")
                .replace("%1", str(position.shape_index + 1))
                .replace("%2", position.shape_id)
            )
        return result
