"""State machine for a frozen virtual review page list."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Set

from .models import VirtualReviewPage


@dataclass(frozen=True)
class NavigationResult:
    """Outcome of starting or moving within a virtual review session."""

    page: Optional[VirtualReviewPage]
    index: int
    total: int
    boundary: bool = False
    skipped_page_ids: tuple[str, ...] = ()
    message: str = ""


class VirtualReviewSession:
    """Hold an immutable page snapshot and a current cursor."""

    def __init__(self) -> None:
        """Initialize an inactive session."""

        self._pages: tuple[VirtualReviewPage, ...] = ()
        self._index = -1

    @property
    def active(self) -> bool:
        """Return whether a page list is active."""

        return bool(self._pages) and self._index >= 0

    @property
    def pages(self) -> tuple[VirtualReviewPage, ...]:
        """Return the frozen page snapshot."""

        return self._pages

    @property
    def index(self) -> int:
        """Return the zero-based current index, or ``-1`` when inactive."""

        return self._index

    @property
    def current(self) -> Optional[VirtualReviewPage]:
        """Return the current page, if any."""

        if not self.active:
            return None
        return self._pages[self._index]

    @staticmethod
    def _page_survives(
        page: VirtualReviewPage,
        available_shape_ids: Optional[Set[str]],
    ) -> bool:
        """Return whether at least one task anchor of the page survives.

        A page is skipped only when every one of its task anchors has
        disappeared; partially deleted pages stay reviewable.
        """

        if available_shape_ids is None:
            return True
        return any(
            anchor_id in available_shape_ids for anchor_id in page.anchor_ids
        )

    def start(self, pages: Iterable[VirtualReviewPage]) -> NavigationResult:
        """Replace the snapshot and select its first page."""

        self._pages = tuple(pages)
        self._index = 0 if self._pages else -1
        if not self._pages:
            return NavigationResult(None, -1, 0, message="no_pages")
        return NavigationResult(self.current, 0, len(self._pages))

    def stop(self) -> None:
        """Clear the session and its cursor."""

        self._pages = ()
        self._index = -1

    def move(
        self,
        delta: int,
        available_shape_ids: Optional[Set[str]] = None,
    ) -> NavigationResult:
        """Move by one direction, skipping fully deleted pages."""

        if not self.active:
            return NavigationResult(None, -1, 0, message="inactive")
        if delta == 0:
            return NavigationResult(
                self.current, self._index, len(self._pages)
            )
        step = 1 if delta > 0 else -1
        skipped: list[str] = []
        candidate = self._index
        if not self._page_survives(
            self._pages[candidate], available_shape_ids
        ):
            skipped.append(self._pages[candidate].page_id)
        candidate += step
        while 0 <= candidate < len(self._pages):
            page = self._pages[candidate]
            if self._page_survives(page, available_shape_ids):
                self._index = candidate
                return NavigationResult(
                    page,
                    candidate,
                    len(self._pages),
                    skipped_page_ids=tuple(skipped),
                )
            skipped.append(page.page_id)
            candidate += step

        return NavigationResult(
            self.current,
            self._index,
            len(self._pages),
            boundary=True,
            skipped_page_ids=tuple(skipped),
            message="first_page" if step < 0 else "last_page",
        )


__all__ = ["NavigationResult", "VirtualReviewSession"]
