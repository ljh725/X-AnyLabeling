"""Incremental Qt model updates and automatic reading-position retention."""

import sqlite3

from PyQt6 import QtCore

from .page_diff import compare_pages, identity


class IncrementalModel:
    """Apply row edits while Qt retains persistent selections and indexes."""

    def sync_items(self, items: tuple, errors: dict) -> set:
        """Update a bounded page, returning identities needing image work."""
        items = tuple(items)
        diff = compare_pages(self._items, items)
        old_images = {
            identity(ref): self._images.get(self.item_key(ref))
            for ref in self._items
        }
        old_errors = {
            identity(ref): self._render_errors.get(self.item_key(ref))
            for ref in self._items
        }
        root = QtCore.QModelIndex()
        for row in range(len(self._items) - 1, -1, -1):
            if identity(self._items[row]) in diff.removed:
                self.beginRemoveRows(root, row, row)
                self._items = self._items[:row] + self._items[row + 1 :]
                self.endRemoveRows()
        for row, ref in enumerate(items):
            key = identity(ref)
            position = next(
                (
                    i
                    for i, value in enumerate(self._items)
                    if identity(value) == key
                ),
                None,
            )
            if position is None:
                self.beginInsertRows(root, row, row)
                self._items = self._items[:row] + (ref,) + self._items[row:]
                self.endInsertRows()
            elif position != row:
                self.beginMoveRows(root, position, position, root, row)
                values = list(self._items)
                values.insert(row, values.pop(position))
                self._items = tuple(values)
                self.endMoveRows()
        self._items = items
        self._images = {
            self.item_key(ref): old_images[identity(ref)]
            for ref in items
            if old_images.get(identity(ref)) is not None
            and identity(ref) not in diff.images
        }
        self._render_errors = {
            self.item_key(ref): old_errors[identity(ref)]
            for ref in items
            if old_errors.get(identity(ref))
            and identity(ref) not in diff.images
        }
        for row, ref in enumerate(items):
            key = identity(ref)
            if key in diff.changed or errors.get(
                key
            ) != self._mutation_errors.get(key):
                self.dataChanged.emit(self.index(row, 0), self.index(row, 0))
        self._mutation_errors = dict(errors)
        return set(diff.added | diff.images)


class IncrementalBrowser:
    """Separate automatic synchronization from explicit page navigation."""

    def _sync_page(self) -> None:
        """Requery a bounded page without clearing unchanged image cards."""
        try:
            self._synchronize_page()
        except (ValueError, sqlite3.Error) as exc:
            self.advanced.feedback.setText(str(exc))
            self._set_relabel_refresh_pending(True)

    def _synchronize_page(self) -> None:
        """Apply a query snapshot synchronously without a stale scroll callback."""
        if (
            self._closed
            or not self._index_is_ready()
            or not self._selected_label
        ):
            return
        old = self._model._items
        visible = [
            (ref, self.view.visualRect(self._model.index(row, 0)).top())
            for row, ref in enumerate(old)
            if self.view.visualRect(self._model.index(row, 0)).intersects(
                self.view.viewport().rect()
            )
        ]
        page = self._query_page(
            self._selected_label, self._page_size, self._page * self._page_size
        )
        target = {identity(ref) for ref in page.items}
        anchor = next(
            ((r, y) for r, y in visible if identity(r) in target), None
        )
        if anchor is None and visible:
            start = old.index(visible[0][0])
            candidates = old[start:] + tuple(reversed(old[:start]))
            for ref in candidates:
                candidate = self._query_page(
                    self._selected_label,
                    self._page_size,
                    page.offset,
                    identity(ref),
                )
                if any(identity(r) == identity(ref) for r in candidate.items):
                    page = candidate
                    anchor = ref, visible[0][1]
                    break
        last = max(0, (page.total - 1) // self._page_size)
        if page.offset // self._page_size > last:
            page = self._query_page(
                self._selected_label, self._page_size, last * self._page_size
            )
        current = self._model.ref_at(self.view.currentIndex().row())
        current_row = self.view.currentIndex().row()
        changed = old != page.items
        self._programmatic_selection = True
        try:
            needs_images = self._model.sync_items(
                page.items, self._mutation_errors
            )
            self._restore_retained_selection()
            if current and not any(
                identity(r) == identity(current) for r in page.items
            ):
                candidates = old[current_row + 1 :] + tuple(
                    reversed(old[:current_row])
                )
                next_ref = next(
                    (
                        r
                        for r in candidates
                        if identity(r)
                        in {identity(value) for value in page.items}
                    ),
                    None,
                )
                if next_ref:
                    row = next(
                        i
                        for i, r in enumerate(page.items)
                        if identity(r) == identity(next_ref)
                    )
                    self.view.selectionModel().setCurrentIndex(
                        self._model.index(row, 0),
                        QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
        finally:
            self._programmatic_selection = False
        self._page = page.offset // self._page_size
        self._current_total = page.total
        self._sync_label_counts()
        self._update_page_controls()
        if changed:
            self.view.doItemsLayout()
            if anchor:
                for row, ref in enumerate(page.items):
                    if identity(ref) == identity(anchor[0]):
                        delta = (
                            self.view.visualRect(
                                self._model.index(row, 0)
                            ).top()
                            - anchor[1]
                        )
                        bar = self.view.verticalScrollBar()
                        bar.setValue(bar.value() + delta)
                        break
            elif old:
                self.advanced.feedback.setText(
                    self.tr(
                        "Reading position adjusted to the nearest available page."
                    )
                )
        self._renderer.retain(page.items)
        notified = {
            ref.image_path
            for ref in page.items
            if ref.image_path in self._changed_files
        }
        self._changed_files.clear()
        self._renderer.check_sources(notified)
        self._renderer.retry(
            r for r in page.items if identity(r) in needs_images
        )
        keys = {self._model.item_key(r) for r in page.items}
        self._render_requested.intersection_update(keys)
        self._render_finished = {
            k: v for k, v in self._render_finished.items() if k in keys
        }
        self._render_finished.update({key: False for key in self._model._images})
        self._render_finished.update({key: True for key in self._model._render_errors})
        for ref in page.items:
            if identity(ref) in needs_images:
                self._render_finished.pop(self._model.item_key(ref), None)
        self._set_relabel_refresh_pending(False)
        self._update_selection_summary()
        self._update_render_progress()
        if changed:
            self._visible_timer.start(0)

    def _sync_label_counts(self) -> None:
        """Update counts without selecting a different observation label."""
        counts = dict(self._controller.query_label_counts())
        counts.setdefault(self._selected_label, 0)
        blocker = QtCore.QSignalBlocker(self.label_combo)
        self.label_combo.clear()
        for label, count in sorted(counts.items()):
            self.label_combo.addItem(f"{label} ({count})", label)
        self.label_combo.setCurrentIndex(
            self.label_combo.findData(self._selected_label)
        )
        del blocker

    def _on_source_images_changed(self, paths: list) -> None:
        """Refresh crops only for images whose source bytes may have changed."""
        refs = [ref for ref in self._model._items if ref.image_path in paths]
        for ref in refs:
            key = self._model.item_key(ref)
            self._model._images.pop(key, None)
            self._model._render_errors.pop(key, None)
            self._render_finished.pop(key, None)
        self._renderer.retry(refs)
        self._visible_timer.start(0)
