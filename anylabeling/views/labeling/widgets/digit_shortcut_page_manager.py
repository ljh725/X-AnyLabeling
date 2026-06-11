"""
Digit Shortcut Page Manager Module

This module provides functionality for managing paged digit shortcuts.
It allows extending the original 10 digit shortcuts (0-9) to multiple pages,
enabling users to configure more shortcuts while maintaining backward
compatibility.

When only one page is configured, behavior is identical to the original
single-page system.

Classes:
    - DigitShortcutPageManager: Core logic for page management and index
      calculation
"""

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from PyQt6 import QtCore

# Use logging instead of print statements for debugging
logger = logging.getLogger(__name__)


class DigitShortcutPageManager(QtCore.QObject):
    """
    Manager class for digit shortcut pagination.

    This class encapsulates the core logic for:
    - Managing page state (current page, total pages)
    - Calculating actual shortcut indices from digit keys
    - Synchronizing page state between components
    - Providing page information for UI display

    Signals:
        page_changed: Emitted when the current page changes, with
                      (new_page, total_pages)

    Attributes:
        PAGE_SIZE: Number of shortcuts per page (constant: 10)
    """

    # Constants
    PAGE_SIZE: int = 10
    DEFAULT_PAGES: int = 1  # Default to single page for backward compatibility

    # Signal emitted when page changes: (current_page, total_pages)
    page_changed = QtCore.pyqtSignal(int, int)

    def __init__(
        self,
        config: Dict[str, Any],
        shortcuts: Optional[Dict[int, Dict[str, str]]] = None,
        status_callback: Optional[Callable[[str, int], None]] = None,
        tr_callback: Optional[Callable[[str], str]] = None,
    ):
        """
        Initialize the DigitShortcutPageManager.

        Args:
            config: Application configuration dictionary
            shortcuts: Dictionary of digit shortcuts
                       (index -> {mode, label})
            status_callback: Callable for displaying status messages
                             (message, duration_ms)
            tr_callback: Callable for translation
        """
        super().__init__()

        self._config = config
        self._shortcuts = shortcuts or {}
        self._status = status_callback
        self._tr = tr_callback or (lambda x: x)

        # Initialize page state
        self._current_page: int = 0
        self._total_pages: int = self._calculate_total_pages()

        logger.debug(
            "DigitShortcutPageManager initialized: "
            "pages=%d, shortcuts=%d",
            self._total_pages,
            len(self._shortcuts),
        )

    def _calculate_total_pages(self) -> int:
        """
        Calculate the total number of pages needed.

        Returns:
            Total pages based on config and existing shortcuts
        """
        # Get configured pages (default to 1 for backward compatibility)
        config_pages = self._config.get(
            "digit_shortcut_pages", self.DEFAULT_PAGES
        )
        try:
            config_pages = max(1, int(config_pages))
        except (TypeError, ValueError):
            config_pages = self.DEFAULT_PAGES

        # Calculate required pages based on existing shortcuts
        required_pages = config_pages
        if self._shortcuts:
            try:
                max_index = max(self._shortcuts.keys())
                required_pages = max(
                    required_pages, (max_index // self.PAGE_SIZE) + 1
                )
            except (TypeError, ValueError):
                pass

        return required_pages

    @property
    def current_page(self) -> int:
        """Get the current page index (0-based)."""
        return self._current_page

    @current_page.setter
    def current_page(self, value: int) -> None:
        """Set the current page index with bounds checking."""
        new_page = max(0, min(value, self._total_pages - 1))
        if new_page != self._current_page:
            self._current_page = new_page
            self.page_changed.emit(self._current_page, self._total_pages)

    @property
    def total_pages(self) -> int:
        """Get the total number of pages."""
        return self._total_pages

    @total_pages.setter
    def total_pages(self, value: int) -> None:
        """Set the total number of pages."""
        self._total_pages = max(1, value)
        # Ensure current page is within bounds
        if self._current_page >= self._total_pages:
            self._current_page = self._total_pages - 1

    @property
    def page_size(self) -> int:
        """Get the page size (read-only constant)."""
        return self.PAGE_SIZE

    @property
    def is_single_page(self) -> bool:
        """Check if only single page mode is active (original behavior)."""
        return self._total_pages <= 1

    def get_actual_index(self, digit_num: int) -> int:
        """
        Calculate the actual shortcut index from a digit key press.

        This is the core method that maps physical key presses (0-9) to
        logical shortcut indices based on the current page.

        Args:
            digit_num: The digit key pressed (0-9)

        Returns:
            The actual shortcut index (0-19 for 2 pages, etc.)

        Example:
            Page 0, digit 5 -> index 5
            Page 1, digit 5 -> index 15
        """
        if not 0 <= digit_num <= 9:
            logger.warning(
                "Invalid digit_num: %d, expected 0-9", digit_num
            )
            return digit_num

        return self._current_page * self.PAGE_SIZE + digit_num

    def switch_page(self) -> Tuple[int, int]:
        """
        Switch to the next page (circular).

        Returns:
            Tuple of (new_page_index, total_pages)
        """
        if self._total_pages <= 1:
            if self._status:
                self._status(
                    self._tr(
                        "仅配置了一页数字快捷键。"
                        "请通过 数字快捷键管理器(Alt+D) 增加页数"
                    ),
                    3000,
                )
            return (self._current_page, self._total_pages)

        old_page = self._current_page
        self._current_page = (
            self._current_page + 1
        ) % self._total_pages

        logger.debug(
            "Page switched: %d -> %d (total: %d)",
            old_page + 1,
            self._current_page + 1,
            self._total_pages,
        )

        # Emit signal for UI updates
        self.page_changed.emit(self._current_page, self._total_pages)

        return (self._current_page, self._total_pages)

    def get_page_info(self) -> Dict[str, Any]:
        """
        Get current page information for UI display.

        Returns:
            Dictionary containing:
                - current_page: Current page index (0-based)
                - display_page: Current page for display (1-based)
                - total_pages: Total number of pages
                - start_index: First shortcut index on current page
                - end_index: Last shortcut index on current page
                - is_single_page: Whether single page mode is active
        """
        start_index = self._current_page * self.PAGE_SIZE
        end_index = start_index + self.PAGE_SIZE - 1

        return {
            "current_page": self._current_page,
            "display_page": self._current_page + 1,
            "total_pages": self._total_pages,
            "start_index": start_index,
            "end_index": end_index,
            "is_single_page": self.is_single_page,
        }

    def get_status_message(self, switch_key: str = "F1") -> str:
        """
        Generate a status message for the current page state.

        Args:
            switch_key: The key used to switch pages

        Returns:
            Formatted status message string
        """
        info = self.get_page_info()

        mapping_text = self._tr("按键 0-9 → 快捷键 {start}-{end}").format(
            start=info["start_index"],
            end=info["end_index"],
        )

        status_message = self._tr(
            "数字快捷键：第 {page}/{total} 页（{mapping}）"
        ).format(
            page=info["display_page"],
            total=info["total_pages"],
            mapping=mapping_text,
        )

        hint_message = self._tr("按 {key} 切换页面").format(
            key=switch_key
        )

        return f"{status_message} - {hint_message}"

    def show_page_switch_status(self, switch_key: str = "F1") -> None:
        """
        Display page switch status message.

        Args:
            switch_key: The key used to switch pages
        """
        if self._status:
            message = self.get_status_message(switch_key)
            self._status(message, 5000)

    def update_shortcuts(self, shortcuts: Dict[int, Dict[str, str]]) -> None:
        """
        Update the shortcuts dictionary and recalculate pages if needed.

        Args:
            shortcuts: New shortcuts dictionary
        """
        self._shortcuts = shortcuts or {}
        new_total = self._calculate_total_pages()

        if new_total != self._total_pages:
            self._total_pages = new_total
            # Ensure current page is within bounds
            if self._current_page >= self._total_pages:
                self._current_page = max(0, self._total_pages - 1)
            self.page_changed.emit(self._current_page, self._total_pages)

    def sync_from_config(self) -> None:
        """
        Synchronize state from configuration.

        Call this after config changes to update page count.
        """
        self._total_pages = self._calculate_total_pages()
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)

    def sync_to_config(self) -> None:
        """
        Synchronize state to configuration.

        Call this before saving config to persist page settings.
        """
        self._config["digit_shortcut_pages"] = self._total_pages

    def reset(self) -> None:
        """Reset to initial state (page 0)."""
        if self._current_page != 0:
            self._current_page = 0
            self.page_changed.emit(self._current_page, self._total_pages)
