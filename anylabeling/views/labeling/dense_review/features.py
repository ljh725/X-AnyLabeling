"""Card observation, preferences and accessible workspace controls."""

import math

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import user_config
from anylabeling.services.dense_review.preferences import normalize_preferences
from anylabeling.services.dense_review.display import (
    RoleStyle,
    default_role_styles,
)


class WorkspaceFeatures:
    """View-only additions sharing the existing session and editable canvas."""

    def _build_observation_controls(self, layout):
        self._association_owners = {}
        self._association_image = ""
        self.crop_mode = QtWidgets.QComboBox()
        self.crop_mode.addItem(self.tr("查看全部关联点"), "all")
        self.crop_mode.addItem(self.tr("主体观察"), "body")
        self.crop_mode.currentIndexChanged.connect(self._on_context_changed)
        self.observation_note = QtWidgets.QLabel()
        self.observation_note.setWordWrap(True)
        self.view_canvas_button = QtWidgets.QPushButton(
            self.tr("在主画布查看")
        )
        self.view_canvas_button.clicked.connect(self._focus_current)
        self.overlap_button = QtWidgets.QPushButton(self.tr("选择重叠对象"))
        self.overlap_button.setToolTip(
            self.tr("也可在主画布按 Ctrl+Alt 并单击")
        )
        self.overlap_button.clicked.connect(self._choose_current_overlap)
        self.retry_thumbnail_button = QtWidgets.QPushButton(
            self.tr("重试图块")
        )
        self.retry_thumbnail_button.clicked.connect(self._retry_current_crop)
        row = QtWidgets.QHBoxLayout()
        for widget in (
            self.crop_mode,
            self.view_canvas_button,
            self.overlap_button,
            self.retry_thumbnail_button,
        ):
            row.addWidget(widget)
        layout.addLayout(row)
        layout.addWidget(self.observation_note)
        self.association_owner = QtWidgets.QComboBox()
        self.association_owner.setAccessibleName(self.tr("关联观察主框"))
        self.association_owner.activated.connect(
            self._choose_observation_owner
        )
        layout.addWidget(self.association_owner)
        self.child_objects = QtWidgets.QComboBox()
        self.child_objects.setAccessibleName(self.tr("关联点与未关联对象"))
        self.child_objects.activated.connect(self._navigate_child)
        layout.addWidget(self.child_objects)
        self.role_combo = QtWidgets.QComboBox()
        for text, role in (
            (self.tr("当前对象"), "current"),
            (self.tr("本批对象"), "batch"),
            (self.tr("其他对象"), "other"),
        ):
            self.role_combo.addItem(text, role)
        self.component_combo = QtWidgets.QComboBox()
        for text, component in (
            (self.tr("轮廓"), "outline"),
            (self.tr("填充"), "fill"),
            (self.tr("点标记"), "points"),
            (self.tr("编辑手柄"), "handles"),
            (self.tr("类别文字"), "text"),
            (self.tr("文字底板"), "text_plate"),
            (self.tr("属性"), "attributes"),
            (self.tr("关联线"), "linking"),
            (self.tr("遮罩"), "mask"),
        ):
            self.component_combo.addItem(text, component)
        self.component_strength = QtWidgets.QSpinBox()
        self.component_strength.setRange(0, 100)
        self.component_strength.setSuffix("%")
        display_row = QtWidgets.QHBoxLayout()
        for widget in (
            self.role_combo,
            self.component_combo,
            self.component_strength,
        ):
            display_row.addWidget(widget)
        layout.addLayout(display_row)
        self.role_combo.currentIndexChanged.connect(
            self._sync_strength_control
        )
        self.component_combo.currentIndexChanged.connect(
            self._sync_strength_control
        )
        self.component_strength.valueChanged.connect(self._change_strength)
        self._task_display_preferences = {}
        self.coverage_points_checkbox = QtWidgets.QCheckBox(
            self.tr("查漏时显示点")
        )
        self.coverage_points_checkbox.toggled.connect(
            self.host.refresh_dense_review_display
        )
        layout.addWidget(self.coverage_points_checkbox)
        # Every primary action has a screen-reader label and a predictable
        # insertion/tab order. Full text remains available when constrained.
        for widget in self.findChildren(QtWidgets.QWidget):
            text = getattr(widget, "text", None)
            if callable(text) and isinstance(
                widget, (QtWidgets.QAbstractButton, QtWidgets.QLabel)
            ):
                widget.setAccessibleName(widget.accessibleName() or text())
                if not widget.toolTip():
                    widget.setToolTip(text())

    def _choose_current_overlap(self):
        item = self.session.current_object() if self.session else None
        if item is None:
            return
        x0, y0, x1, y1 = item.bounds
        self.host.canvas.choose_dense_review_candidate(
            QtCore.QPointF((x0 + x1) / 2, (y0 + y1) / 2)
        )

    def _sync_strength_control(self):
        role = self.role_combo.currentData()
        component = self.component_combo.currentData()
        style = self.host._dense_review_role_styles.get(
            role, default_role_styles()[role]
        )
        with QtCore.QSignalBlocker(self.component_strength):
            self.component_strength.setValue(
                round(getattr(style, component) * 100)
            )

    def _change_strength(self, value):
        role = self.role_combo.currentData()
        style = self.host._dense_review_role_styles.get(
            role, default_role_styles()[role]
        )
        values = style.to_dict()
        values[self.component_combo.currentData()] = value / 100
        self.host._dense_review_role_styles[role] = RoleStyle.from_dict(values)
        self.host.refresh_dense_review_display()

    def _capture_display_preferences(self):
        self._task_display_preferences[self._task_id] = {
            "mode": self.display_combo.currentData(),
            "show_points": self.coverage_points_checkbox.isChecked(),
            "styles": {
                role: style.to_dict()
                for role, style in self.host._dense_review_role_styles.items()
            },
        }

    def _apply_display_preferences(self, task_id):
        prefs = self._task_display_preferences.get(task_id, {})
        self.coverage_points_checkbox.setVisible(task_id == self.TASK_COVERAGE)
        with QtCore.QSignalBlocker(self.coverage_points_checkbox):
            self.coverage_points_checkbox.setChecked(
                bool(prefs.get("show_points", False))
                if isinstance(prefs, dict)
                else False
            )
        if not isinstance(prefs, dict):
            return
        styles = prefs.get("styles", {})
        if isinstance(styles, dict):
            self.host._dense_review_role_styles.update(
                {
                    role: RoleStyle.from_dict(values)
                    for role, values in styles.items()
                    if role in default_role_styles()
                    and isinstance(values, dict)
                }
            )
        mode = prefs.get("mode")
        if mode in ("focus", "all", "original"):
            self._set_display_mode_widget(mode)
        self.host.refresh_dense_review_display()
        self._sync_strength_control()

    def _group_members(self, item):
        if item.group_id is None:
            return []
        return self._observation_groups().get(str(item.group_id), [])

    def _observation_groups(self):
        if getattr(self, "_observation_group_map", None) is None:
            groups = {}
            for obj in self.session.state.objects.values():
                if obj.group_id is not None:
                    groups.setdefault(str(obj.group_id), []).append(obj)
            self._observation_group_map = groups
            self._observation_group_rectangles = {
                key: [obj for obj in values if obj.shape_type == "rectangle"]
                for key, values in groups.items()
            }
        return self._observation_group_map

    def _card_parent(self, item):
        if item.shape_type == "rectangle":
            return item
        self._observation_groups()
        rectangles = self._observation_group_rectangles.get(
            str(item.group_id), []
        )
        if len(rectangles) == 1:
            return rectangles[0]
        owner = self._association_owners.get(str(item.group_id))
        return next((obj for obj in rectangles if obj.shape_id == owner), item)

    def _card_points(self, item):
        if item.shape_type != "rectangle":
            return []
        members = self._group_members(item)
        rectangles = [obj for obj in members if obj.shape_type == "rectangle"]
        if (
            len(rectangles) != 1
            and self._association_owners.get(str(item.group_id))
            != item.shape_id
        ):
            return []
        return [obj for obj in members if obj.shape_type == "point"]

    def _crop_bounds(self, item):
        """Return the actual evidence bounds, independent of card height."""
        bounds = tuple(item.bounds)
        if not all(math.isfinite(value) for value in bounds):
            return bounds
        if item.shape_type == "point":
            x, y = bounds[:2]
            return (x - 24, y - 24, x + 24, y + 24)
        if self.crop_mode.currentData() != "all":
            return bounds
        for point in self._card_points(item):
            if all(math.isfinite(value) for value in point.bounds):
                x, y = point.bounds[:2]
                bounds = (
                    min(bounds[0], x),
                    min(bounds[1], y),
                    max(bounds[2], x),
                    max(bounds[3], y),
                )
        return bounds

    def _crop_version(self, item):
        """Bind pixels to current object and associated geometry versions."""
        from anylabeling.services.dense_review.models import signature_for

        return signature_for(
            {
                "image": self.host.dense_review_image_info()[0],
                "geometry": item.geometry_signature,
                "group": item.group_id,
                "points": [
                    (point.shape_id, point.geometry_signature)
                    for point in self._card_points(item)
                ],
            }
        )

    def _refresh_observation(self):
        if self._association_image != (self.host.filename or ""):
            self._association_image = self.host.filename or ""
            self._association_owners.clear()
        current = self.session.current_object() if self.session else None
        self.child_objects.clear()
        self.association_owner.clear()
        if current is None:
            return
        parent = self._card_parent(current)
        self.child_objects.addItem(self.tr("选择对象以定位"), "")
        points = self._card_points(parent)
        # Include every otherwise unreachable object, once, with a stable id.
        loose = [
            obj
            for obj in self.session.state.objects.values()
            if obj.shape_type != "rectangle" and self._card_parent(obj) is obj
        ]
        seen = set()
        for obj in [parent, *points, *loose]:
            if obj.shape_id in seen:
                continue
            seen.add(obj.shape_id)
            self.child_objects.addItem(
                f"#{obj.display_index} {obj.label} · {obj.shape_type}",
                obj.shape_id,
            )
        for obj in self._group_members(current):
            if obj.shape_type == "rectangle":
                self.association_owner.addItem(
                    f"#{obj.display_index} {obj.label}", obj.shape_id
                )
        self.association_owner.setVisible(self.association_owner.count() > 1)
        x0, y0, x1, y1 = parent.bounds
        outside = [
            obj
            for obj in points
            if not (x0 <= obj.bounds[0] <= x1 and y0 <= obj.bounds[1] <= y1)
        ]
        bounds = self._crop_bounds(parent)
        crop_width = max(1, bounds[2] - bounds[0])
        crop_height = max(1, bounds[3] - bounds[1])
        limited = (
            self._card_cell_size().width() - 20
        ) / crop_width < self.card_image_height / crop_height
        notes = [self.tr("关联点 {n} · 点审核待支持").format(n=len(points))]
        if outside:
            notes.append(self.tr("关联点超出人物范围"))
        if any(
            not (
                0 <= obj.bounds[0] <= self.session.state.image_width
                and 0 <= obj.bounds[1] <= self.session.state.image_height
            )
            for obj in points
        ):
            notes.append(self.tr("关联点超出图像范围"))
        if limited:
            notes.append(self.tr("受面板宽度限制，可拉宽或浮动面板"))
        if self.association_owner.count() > 1:
            notes.append(self.tr("关联待确认：选择观察主框不修改正式分组"))
        self.observation_note.setText(" · ".join(notes))
        self.observation_note.setToolTip(self.observation_note.text())
        selected_child = self.child_objects.findData(current.shape_id)
        if selected_child >= 0:
            self.child_objects.setCurrentIndex(selected_child)

    def _navigate_child(self, index):
        shape_id = self.child_objects.itemData(index)
        if not shape_id or self.session is None:
            return
        self._navigate_to(self._current_batch_id(), shape_id)

    def _on_canvas_review_selection(self, shapes):
        if self._updating or not self.isVisible() or self.session is None:
            return
        if len(shapes) != 1:
            return
        shape_id = getattr(shapes[0], "xanylabeling_shape_id", "")
        if not shape_id or shape_id == self._current_shape_id():
            return
        batch = self._current_batch_id()
        item = self.session.object(shape_id)
        parent = self._card_parent(item) if item is not None else None
        batch_target = parent.shape_id if parent is not None else shape_id
        for candidate in self.session.state.batches:
            if batch_target in self.session.state.member_ids(candidate.batch_id):
                batch = candidate.batch_id
                break
        self.session.set_current(batch, shape_id)
        self.refresh_all()

    def _choose_observation_owner(self, index):
        shape_id = self.association_owner.itemData(index)
        item = self.session.object(shape_id) if self.session else None
        if item is not None:
            self._association_owners[str(item.group_id)] = shape_id
            self._navigate_to(self._current_batch_id(), shape_id)
            self._on_context_changed()

    def _retry_current_crop(self):
        shape_id = self._current_shape_id()
        if shape_id in self._failed_ids:
            self._retrying_failed_ids.add(shape_id)
        self._failed_ids.discard(shape_id)
        self.thumbnails.invalidate_shape(shape_id)
        self._card_model.clear_failed(shape_id)
        self._schedule_visible_thumbnails()

    def _reset_failed_context(self):
        """Keep known failures excluded until a current retry succeeds."""
        context = (
            self.host.filename,
            getattr(self.host, "output_dir", ""),
            id(self.session),
        )
        if (
            context != getattr(self, "_failure_context", None)
            or self.session is None
        ):
            self._retrying_failed_ids.clear()
        else:
            self._retrying_failed_ids.update(self._failed_ids)
        self._failure_context = context
        self._failed_ids.clear()

    def _restore_review_preferences(self):
        prefs = normalize_preferences(
            self.host._config.get("dense_review", {})
        )
        self._task_display_preferences = prefs["task_display"]
        self._task_id = prefs.get("task", self.TASK_CATEGORY)
        if self._task_id not in self.TASK_IDS:
            self._task_id = self.TASK_CATEGORY
        self.set_card_image_height(prefs.get("image_height", 320))
        self.context_spin.setValue(prefs.get("context", 35))
        self.set_batches_visible(prefs.get("batches_visible", True))
        self.set_cards_visible(prefs.get("cards_visible", True))

    def _save_review_preferences(self):
        """Save view fields without a modal failure or annotation dirty edit."""
        self.host.dense_review_end_hold_on_blur()
        self._capture_display_preferences()
        prefs = {
            "task": self._task_id,
            "image_height": self.card_image_height,
            "context": self.context_spin.value(),
            "batches_visible": self._batches_visible,
            "cards_visible": self._cards_visible,
            "task_display": self._task_display_preferences,
        }
        try:
            user_config.save_patch(
                user_config.ConfigPatch(
                    {
                        f"dense_review.{key}": value
                        for key, value in prefs.items()
                    }
                )
            )
        except user_config.ConfigError as error:
            self._status(
                self.tr("复核偏好保存失败：{error}").format(error=error)
            )
            return False
        settings = self.host.settings
        settings.setValue("dense_review/geometry", self.saveGeometry())
        settings.setValue("dense_review/floating", self.isFloating())
        settings.setValue("dense_review/width", self.width())
        settings.sync()
        if settings.status() != QtCore.QSettings.Status.NoError:
            self._status(
                self.tr("复核偏好保存失败：{error}").format(error="QSettings")
            )
            return False
        return True

    def _restore_review_geometry(self):
        settings = self.host.settings
        geometry = settings.value("dense_review/geometry")
        if settings.value("dense_review/floating", False, type=bool):
            self.setFloating(True)
            if geometry:
                self.restoreGeometry(geometry)
            screens = QtGui.QGuiApplication.screens()
            visible = [screen.availableGeometry() for screen in screens]
            if not any(
                area.contains(self.frameGeometry()) for area in visible
            ):
                area = (
                    QtGui.QGuiApplication.primaryScreen().availableGeometry()
                )
                self.resize(
                    min(self.width(), area.width()),
                    min(self.height(), area.height()),
                )
                self.move(area.topLeft())
        else:
            window = getattr(self.host, "main_window", None)
            if window is not None and hasattr(window, "resizeDocks"):
                window.resizeDocks(
                    [self],
                    [settings.value("dense_review/width", 480, type=int)],
                    QtCore.Qt.Orientation.Horizontal,
                )

    def _shortcut_allowed(self):
        if not self.isVisible() or self.session is None:
            return False
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        if QtWidgets.QApplication.activeWindow() not in (
            self.window(),
            self.host.window(),
        ):
            return False
        focus = QtWidgets.QApplication.focusWidget()
        return (
            not isinstance(
                focus,
                (
                    QtWidgets.QLineEdit,
                    QtWidgets.QTextEdit,
                    QtWidgets.QPlainTextEdit,
                    QtWidgets.QAbstractSpinBox,
                ),
            )
            and not self._defer_background_cards()
        )

    def _sync_shortcut_context(self, *_args):
        """Enable only the active owner, including its floating dock."""
        enabled = self._shortcut_allowed()
        for shortcut in self._shortcuts:
            shortcut.setEnabled(enabled)

    def _screen_removed(self, _screen):
        if self.isFloating() and self.isVisible():
            self._restore_review_geometry()

    def _setup_review_accessibility(self):
        for widget in self.findChildren(QtWidgets.QWidget):
            if isinstance(widget, QtWidgets.QAbstractButton):
                widget.setAccessibleName(
                    widget.accessibleName() or widget.text()
                )
                widget.setToolTip(widget.toolTip() or widget.text())
        sequence = (
            self.task_selector,
            self.compact_batch_combo,
            self.batch_list,
            self.dimension_combo,
            self.card_list,
            self.child_objects,
            self.view_canvas_button,
            self.complete_batch_button,
            self.complete_object_button,
            self.region_list,
            self.complete_region_button,
            self.close_button,
        )
        for previous, following in zip(sequence, sequence[1:]):
            QtWidgets.QWidget.setTabOrder(previous, following)
