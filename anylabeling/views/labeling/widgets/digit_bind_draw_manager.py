"""Digit bind-draw manager.

Manages the ``bind_draw`` digit-shortcut mode (Feature 2 of the
manual-person-annotation-refinement change). When the user selects a
single ``person`` / ``head`` / ``face`` source shape and presses a digit
key, this manager resolves the target label/shape_type from the existing
``digit_shortcuts`` mapping, resolves/creates a ``group_id``, and enters
draw mode with a pending context. On draw completion, ``consume_pending``
is called by ``LabelWidget.new_shape`` to write the pending label and
group_id onto the new shape, and (if the source had no group_id) backfill
the source within the same undo transaction.

This manager mirrors ``DigitRenameManager`` (plain object, borrows
``label_widget.tr`` for i18n). The two are mutually exclusive digit
modes selected by the ``digit_shortcut_mode`` config key.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

# Labels that participate in person-instance binding.
BIND_LABELS = ("person", "head", "face")

# Only rectangles are accepted as bind targets/sources in v0.
BIND_SHAPE_TYPE = "rectangle"


@dataclass
class BindPendingContext:
    """Transient pending state held between the digit-key press and the
    completion (or cancellation) of the bind-draw.

    Attributes:
        source: The source shape reference (person/head/face). May be
            backfilled with ``gid`` on commit if ``need_backfill``.
        target_label: The new shape's label (from digit mapping).
        target_shape_type: The new shape's shape_type (from mapping).
        gid: The resolved group_id (inherited from source or freshly
            minted).
        need_backfill: True when the source had no group_id and must be
            backfilled with ``gid`` on commit (lazy, transactional).
    """

    source: object
    target_label: str
    target_shape_type: str
    gid: int
    need_backfill: bool


class DigitBindDrawManager:
    """Manage the ``bind_draw`` digit-shortcut mode.

    Symmetric to ``DigitRenameManager``: a plain object that borrows the
    host ``label_widget`` for canvas access, config reads, status hints,
    and ``tr``-based i18n.
    """

    def __init__(self, label_widget) -> None:
        """Initialize the manager.

        Args:
            label_widget: The main labeling widget instance.
        """
        self._label_widget = label_widget
        self._pending: Optional[BindPendingContext] = None

    # ------------------------------------------------------------------
    # Mode gate
    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        """Return whether bind_draw mode is the active digit mode."""
        return (
            self._label_widget._config.get("digit_shortcut_mode")
            == "bind_draw"
        )

    @property
    def pending(self) -> Optional[BindPendingContext]:
        """Expose the current pending context (read-only access)."""
        return self._pending

    # ------------------------------------------------------------------
    # Digit entry point
    # ------------------------------------------------------------------
    def handle_digit(self, digit_num: int) -> bool:
        """Handle a digit key press in bind_draw mode.

        Validates source/target, resolves group_id, records the pending
        context, and enters draw mode. On any rejection, emits a hint and
        returns without entering draw mode.

        Args:
            digit_num: Pressed digit key in the range 0-9.

        Returns:
            True when the bind_draw path handled the key press.
        """
        lw = self._label_widget

        # Reject if a bind is already pending (avoid stacking).
        if self._pending is not None:
            self._hint_pending_active()
            return True

        # Resolve target from the existing digit shortcuts mapping.
        target_label, target_shape_type = self._resolve_target(digit_num)
        if target_label is None:
            self._hint_no_mapping(digit_num)
            return True

        # v0: only rectangle + person/head/face targets are accepted.
        if not self._is_valid_target(target_label, target_shape_type):
            self._hint_invalid_target(
                digit_num, target_label, target_shape_type
            )
            return True

        if self._can_start_unbound_person_instance(
            target_label, target_shape_type
        ):
            self._enter_unbound_person_draw(
                digit_num, target_label, target_shape_type
            )
            return True

        # Validate source: single selected person/head/face.
        source = self._validate_source()
        if source is None:
            # _validate_source already emitted the rejection hint.
            return True

        # Resolve group_id (inherit or mint; record need_backfill).
        gid, need_backfill = self._resolve_gid(source)

        # Pre-check duplicate target label within the group.
        if self._group_has_label(gid, target_label):
            self._hint_duplicate(gid, target_label)
            return True

        # Record pending context (lazy backfill — source unchanged here).
        self._pending = BindPendingContext(
            source=source,
            target_label=target_label,
            target_shape_type=target_shape_type,
            gid=gid,
            need_backfill=need_backfill,
        )

        # Enter draw mode with the pending label.
        lw.digit_to_label = target_label
        lw.toggle_draw_mode(edit=False, create_mode=target_shape_type)

        self._hint_entered_draw(
            digit_num, source, gid, target_label, need_backfill
        )
        return True

    # ------------------------------------------------------------------
    # Pending consumption (called by LabelWidget.new_shape)
    # ------------------------------------------------------------------
    def consume_pending(
        self,
    ) -> Optional[Tuple[str, int, object, bool]]:
        """Return the pending (label, gid, source, need_backfill) tuple,
        after a second duplicate/validity check.

        Returns:
            ``(label, gid, source, need_backfill)`` if a pending bind
            exists and still passes validation; otherwise clears the
            pending context and returns ``None``.
        """
        if self._pending is None:
            return None

        ctx = self._pending

        # Re-validate target shape_type (defensive: config may change).
        if not self._is_valid_target(ctx.target_label, ctx.target_shape_type):
            self._pending = None
            return None

        # Second duplicate check (TOCTOU guard).
        if self._group_has_label(ctx.gid, ctx.target_label):
            self._hint_duplicate(ctx.gid, ctx.target_label)
            self._pending = None
            return None

        # Source may have been deleted mid-draw; drop if gone.
        if ctx.source not in self._label_widget.canvas.shapes:
            self._pending = None
            return None

        return (
            ctx.target_label,
            ctx.gid,
            ctx.source,
            ctx.need_backfill,
        )

    def clear_pending(self) -> None:
        """Drop the pending context without committing.

        Called on draw cancel, image switch, mode switch, or undo. The
        source shape is left untouched (lazy backfill guarantee).
        """
        self._pending = None

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------
    def _resolve_target(
        self, digit_num: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """Read the digit shortcuts mapping for ``digit_num``.

        Returns:
            ``(label, shape_type)`` or ``(None, None)`` if unmapped.
        """
        lw = self._label_widget
        shortcuts = getattr(lw, "drawing_digit_shortcuts", None)
        if shortcuts is None:
            return None, None

        page_mgr = getattr(lw, "digit_page_manager", None)
        if page_mgr is not None:
            idx = page_mgr.get_actual_index(digit_num)
        else:
            idx = digit_num

        data = shortcuts.get(idx)
        if not data:
            return None, None

        label = data.get("label")
        shape_type = data.get("mode")
        if not label or not shape_type:
            return None, None
        return label, shape_type

    @staticmethod
    def _is_valid_target(label: str, shape_type: str) -> bool:
        """Return True only for rectangle + person/head/face targets."""
        return shape_type == BIND_SHAPE_TYPE and label in BIND_LABELS

    def _validate_source(self) -> Optional[object]:
        """Return the single selected person/head/face source, or None.

        Emits a rejection hint and returns None on:
          - no selection
          - multi selection
          - source label not in BIND_LABELS
          - source shape_type != rectangle
        """
        lw = self._label_widget
        selected = list(getattr(lw.canvas, "selected_shapes", []) or [])

        if not selected:
            self._hint_no_source()
            return None
        if len(selected) > 1:
            self._hint_multi_source(len(selected))
            return None

        source = selected[0]
        if getattr(source, "label", None) not in BIND_LABELS:
            self._hint_bad_source_label(getattr(source, "label", None))
            return None
        if getattr(source, "shape_type", None) != BIND_SHAPE_TYPE:
            self._hint_bad_source_type(getattr(source, "shape_type", None))
            return None
        return source

    def _resolve_gid(self, source: object) -> Tuple[int, bool]:
        """Resolve the group_id for the bind.

        If the source already has a group_id, inherit it. Otherwise mint
        a fresh one and flag for lazy backfill on commit.

        Returns:
            ``(gid, need_backfill)``.
        """
        existing = getattr(source, "group_id", None)
        if existing is not None:
            return int(existing), False
        gid = self._label_widget.canvas.gen_new_group_id()
        return gid, True

    def _group_has_label(self, gid: int, label: str) -> bool:
        """Return True if any shape with ``gid`` already has ``label``."""
        canvas = self._label_widget.canvas
        for shape in getattr(canvas, "shapes", []) or []:
            if (
                getattr(shape, "group_id", None) == gid
                and getattr(shape, "label", None) == label
            ):
                return True
        return False

    def _can_start_unbound_person_instance(
        self, target_label: str, target_shape_type: str
    ) -> bool:
        """Return True when a digit can start Feature 1 directly.

        In bind_draw mode, digits normally require a selected source.
        The exception is Feature 1: no selection + person rectangle +
        auto_person_instance enabled means "create a fresh person
        instance", with group_id minted later by LabelWidget.new_shape.
        """
        lw = self._label_widget
        selected = getattr(lw.canvas, "selected_shapes", []) or []
        return (
            not selected
            and target_label == "person"
            and target_shape_type == BIND_SHAPE_TYPE
            and bool(lw._config.get("auto_person_instance"))
        )

    def _enter_unbound_person_draw(
        self, digit: int, target_label: str, target_shape_type: str
    ) -> None:
        """Enter draw mode for a new person instance without bind pending."""
        lw = self._label_widget
        self._pending = None
        lw.digit_to_label = target_label
        lw.toggle_draw_mode(edit=False, create_mode=target_shape_type)
        self._hint_unbound_person_draw(digit)

    # ------------------------------------------------------------------
    # Hint generators (task 4.x). All go through label_widget.status +
    # label_widget.tr, mirroring DigitRenameManager.
    # ------------------------------------------------------------------
    def _status(self, message: str, delay: int = 2500) -> None:
        lw = self._label_widget
        lw.status(lw.tr(message), delay)

    def _hint_no_mapping(self, digit: int) -> None:
        self._status(
            "按键 {d} 未设置绘制映射，请在数字快捷管理器中配置".format(d=digit)
        )

    def _hint_invalid_target(
        self, digit: int, label: str, shape_type: str
    ) -> None:
        self._status(
            "按键 {d} 的目标 {lbl}/{st} 不支持绑定绘制"
            "（仅支持 person/head/face 矩形）".format(
                d=digit, lbl=label, st=shape_type
            )
        )

    def _hint_no_source(self) -> None:
        self._status("请先选中一个 person/head/face 来源对象")

    def _hint_multi_source(self, count: int) -> None:
        self._status(
            "绑定绘制仅支持单选来源（当前选中 {n} 个）".format(n=count)
        )

    def _hint_bad_source_label(self, label: object) -> None:
        self._status("来源对象 {lbl} 不是 person/head/face".format(lbl=label))

    def _hint_bad_source_type(self, shape_type: object) -> None:
        self._status("来源对象类型 {st} 不是 rectangle".format(st=shape_type))

    def _hint_duplicate(self, gid: int, label: str) -> None:
        self._status(
            "组 #{g} 中已存在 {lbl}，已拒绝创建".format(g=gid, lbl=label)
        )

    def _hint_entered_draw(
        self,
        digit: int,
        source: object,
        gid: int,
        target_label: str,
        backfill: bool,
    ) -> None:
        src_label = getattr(source, "label", "?")
        if backfill:
            self._status(
                "按键 {d}：来源 {src} 无 group_id，"
                "绘制完成后将创建并回填组 #{g}，目标 {tgt}".format(
                    d=digit,
                    src=src_label,
                    g=gid,
                    tgt=target_label,
                )
            )
        else:
            self._status(
                "按键 {d}：从 {src} 继承组 #{g}，绘制 {tgt}".format(
                    d=digit,
                    src=src_label,
                    g=gid,
                    tgt=target_label,
                )
            )

    def _hint_unbound_person_draw(self, digit: int) -> None:
        self._status(
            "按键 {d}：未选中来源对象，进入新建 person 模式，"
            "完成后自动生成 group_id".format(d=digit)
        )

    def _hint_pending_active(self) -> None:
        self._status("已有绑定绘制进行中，请先完成或取消")
