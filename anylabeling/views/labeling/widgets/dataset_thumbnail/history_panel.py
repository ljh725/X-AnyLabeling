"""Dockable, paginated history browser with explicit recovery actions."""

from PyQt6 import QtCore, QtWidgets


class HistoryPanel(QtWidgets.QDockWidget):
    """Display durable operations without changing the thumbnail selection."""

    locate_requested = QtCore.pyqtSignal(object)
    preview_requested = QtCore.pyqtSignal(object)
    return_requested = QtCore.pyqtSignal(object)
    restore_requested = QtCore.pyqtSignal(object)
    revert_requested = QtCore.pyqtSignal(object, object)
    import_requested = QtCore.pyqtSignal()

    def __init__(self, store: object, parent: QtWidgets.QWidget) -> None:
        """Build controls whose actions always refer to one operation."""
        super().__init__(self.tr("Operation history"), parent)
        self.setObjectName("thumbnailOperationHistory")
        self.store = store
        self.offset = 0
        body = QtWidgets.QWidget()
        self.setWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(
            self.tr("Search file, old/new label or operation")
        )
        layout.addWidget(self.search)
        dates = QtWidgets.QHBoxLayout()
        self.since = QtWidgets.QLineEdit()
        self.since.setPlaceholderText(self.tr("From date (YYYY-MM-DD)"))
        self.until = QtWidgets.QLineEdit()
        self.until.setPlaceholderText(self.tr("To date (YYYY-MM-DD)"))
        dates.addWidget(self.since)
        dates.addWidget(self.until)
        layout.addLayout(dates)
        self.state = QtWidgets.QComboBox()
        for value, label in (
            ("", "All results"),
            ("completed", "Completed"),
            ("partial", "Partially completed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
            ("unverified", "Needs verification"),
        ):
            self.state.addItem(self.tr(label), value)
        layout.addWidget(self.state)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(
            [
                self.tr("Time / object"),
                self.tr("Operation / before"),
                self.tr("Result / after"),
            ]
        )
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumWidth(330)
        layout.addWidget(self.tree)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        actions = QtWidgets.QGridLayout()
        for index, (label, callback) in enumerate(
            (
                ("Locate object", self._locate),
                ("Preview current image", self._preview),
                ("Return to reading position", self._return),
                ("Restore files from backup", self._restore),
                ("Revert selected changes", self._revert),
            )
        ):
            button = QtWidgets.QPushButton(self.tr(label))
            button.clicked.connect(callback)
            actions.addWidget(button, index // 2, index % 2)
        layout.addLayout(actions)
        pages = QtWidgets.QHBoxLayout()
        for label, step in (("Previous", -50), ("Next", 50)):
            button = QtWidgets.QPushButton(self.tr(label))
            button.clicked.connect(
                lambda _checked=False, n=step: self._page(n)
            )
            pages.addWidget(button)
        layout.addLayout(pages)
        self.import_button = QtWidgets.QPushButton(self.tr("Import existing backups"))
        self.import_button.clicked.connect(self.import_requested)
        layout.addWidget(self.import_button)
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._filter)
        for control in (self.search, self.since, self.until):
            control.textChanged.connect(lambda: self._search_timer.start())
        self.state.currentIndexChanged.connect(self._filter)
        self.refresh()

    def _filter(self) -> None:
        """Start at the first history page for changed filters."""
        self.offset = 0
        self.refresh()

    def _page(self, step: int) -> None:
        """Move through bounded history results."""
        self.offset = max(0, self.offset + step)
        self.refresh()

    def refresh(self) -> None:
        """Reload one history page without touching the primary card grid."""
        self.tree.clear()
        records = self.store.query(
            self.search.text(),
            self.state.currentData(),
            self.since.text(),
            (
                self.until.text() + "T23:59:59.999999+00:00"
                if self.until.text()
                else ""
            ),
            self.offset,
        )
        names = {
            "relabel": self.tr("Relabel"),
            "undo": self.tr("Undo"),
            "review": self.tr("Review state"),
            "revert": self.tr("Revert"),
            "review-revert": self.tr("Revert review state"),
            "restore": self.tr("File recovery"),
        }
        states = {
            key: self.state.itemText(i)
            for i in range(self.state.count())
            if (key := self.state.itemData(i))
        }
        for record in records:
            top = QtWidgets.QTreeWidgetItem(
                [
                    record["created"],
                    names.get(record["kind"], record["kind"]),
                    f'{states.get(record["state"], record["state"])} ({len(record["items"])})',
                ]
            )
            top.setData(0, QtCore.Qt.ItemDataRole.UserRole, record)
            if record.get("legacy"):
                top.setToolTip(0, self.tr("Imported backup; time is manifest modification time."))
            self.tree.addTopLevelItem(top)
            for item in record["items"]:
                child = QtWidgets.QTreeWidgetItem(
                    [
                        item["image_path"]
                        .replace("\\", "/")
                        .rsplit("/", 1)[-1],
                        str(item.get("before", "")),
                        str(item.get("after", "")),
                    ]
                )
                child.setData(0, QtCore.Qt.ItemDataRole.UserRole, item)
                consumed = self.store.consumed(record["id"], item)
                child.setText(
                    2,
                    child.text(2)
                    + " · "
                    + (
                        self.tr("Already reverted")
                        if consumed
                        else self.tr(item.get("status", "unverified"))
                    ),
                )
                child.setToolTip(
                    0,
                    item["image_path"]
                    + "\n#"
                    + item["shape_id"]
                    + "\n"
                    + item.get("message", ""),
                )
                top.addChild(child)
        self.tree.resizeColumnToContents(0)

    def _selection(self) -> tuple:
        """Resolve one operation and its explicitly selected child records."""
        selected = self.tree.selectedItems()
        roots = {id(i.parent() or i): i.parent() or i for i in selected}
        if len(roots) != 1:
            self.message.setText(self.tr("Select objects from one operation."))
            return None, []
        root = next(iter(roots.values()))
        record = root.data(0, QtCore.Qt.ItemDataRole.UserRole)
        items = [
            i.data(0, QtCore.Qt.ItemDataRole.UserRole)
            for i in selected
            if i.parent()
        ]
        return record, items

    def _locate(self) -> None:
        """Navigate only when exactly one historical object is selected."""
        _record, items = self._selection()
        if len(items) == 1:
            self.locate_requested.emit(items[0])

    def _preview(self) -> None:
        """Request an explicitly labeled current-image preview."""
        _record, items = self._selection()
        if len(items) == 1:
            self.preview_requested.emit(items[0])

    def _return(self) -> None:
        """Return to a historical view without restoring its selection."""
        record, _items = self._selection()
        if record:
            self.return_requested.emit(record)

    def _restore(self) -> None:
        """Request guarded file recovery for the selected operation."""
        record, _items = self._selection()
        if record:
            self.restore_requested.emit(record)

    def _revert(self) -> None:
        """Request a separate inverse for explicitly selected effects."""
        record, items = self._selection()
        if record and items:
            self.revert_requested.emit(record, items)
