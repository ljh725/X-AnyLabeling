from PyQt6.QtWidgets import QWidget, QHBoxLayout, QComboBox


class GroupIDFilterComboBox(QWidget):
    def __init__(self, parent=None, items=[]):
        super(GroupIDFilterComboBox, self).__init__(parent)
        self.items = items
        self.gid_box = QComboBox()
        self.gid_box.setToolTip(self.tr("Group ID Filter"))
        self.gid_box.addItems(self.items)
        self.gid_box.currentIndexChanged.connect(parent.gid_selection_changed)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(self.gid_box)
        self.setLayout(layout)

    def update_items(self, items):
        self.items = items
        self.gid_box.clear()
        self.gid_box.addItems(self.items)


class LabelFilterComboBox(QWidget):
    def __init__(self, parent=None, items=[]):
        super(LabelFilterComboBox, self).__init__(parent)
        self.items = items
        self.text_box = QComboBox()
        self.text_box.setToolTip(self.tr("Label Filter"))
        self.text_box.addItems(self.items)
        self.text_box.currentIndexChanged.connect(
            parent.text_selection_changed
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(self.text_box)
        self.setLayout(layout)

    def update_items(self, items):
        self.items = items
        self.text_box.clear()
        self.text_box.addItems(self.items)


class ShapeTypeFilterComboBox(QWidget):
    def __init__(self, parent=None, items=[]):
        super(ShapeTypeFilterComboBox, self).__init__(parent)
        self.items = items
        self.type_box = QComboBox()
        self.type_box.setToolTip(self.tr("Shape Type Filter"))
        self.type_box.addItems(self.items)
        self.type_box.currentIndexChanged.connect(
            parent.shape_type_selection_changed
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(self.type_box)
        self.setLayout(layout)

    def update_items(self, items):
        self.items = items
        self.type_box.clear()
        self.type_box.addItems(self.items)
