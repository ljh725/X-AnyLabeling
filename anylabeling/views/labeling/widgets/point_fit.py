"""Shift-click rectangle fitting for the labeling canvas."""

import math

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from ..rect_edge_click import (
    OPPOSITE_CORNER,
    corner_point,
    point_fit_decision,
    point_fit_inside_box,
    point_fit_lock_decision,
    proposed_inward_point_fit_box,
    proposed_point_fit_box,
)
from ..rectangle_preview import (
    FIT_CANDIDATE_COLOR,
    FIT_CANDIDATE_WIDTH,
    PointFitPreview,
    build_remaining_outline,
    rectangle_box_from_points,
)
from ..shape import Shape

ENTRY_NATIVE = "native"
ENTRY_LOCK = "lock"
ENTRY_FINISHED = "finished"
INVALID_CANDIDATE_COLOR = "#ff5c5c"

# One Shift round starts either inside the rectangle (the corner is locked
# right away) or outside/on the outline (the classic click fit previews
# first and locks the first clear zone the pointer reaches). Both entries
# end the round as ``finished`` so a held Shift never reopens it.


class PointFitMixin:
    """Own point-fit state, preview, and commit behavior."""

    def _clear_point_fit(
        self, keep_press: bool = False, keep_lock: bool = False
    ) -> None:
        """Clear the preview, the locked corner, and press state.

        ``keep_press`` keeps the release the fit is still owed after a
        cancel; the press itself no longer drifts the gesture. An already
        cancelled gesture keeps waiting for that same release, so repeated
        clears never drop it. ``keep_lock`` keeps the accepted corner and
        its original geometry, so a retrying click keeps the same anchor.
        """
        if self._point_fit_cursor is not None:
            self.setToolTip("")
        self._point_fit_target = None
        self._point_fit_start = None
        self._point_fit_pending_box = None
        self._point_fit_cursor = None
        self._point_fit_anchor = None
        self._point_fit_corner = None
        self._point_fit_hover_corner = None
        self._point_fit_box = None
        self._point_fit_source_target = None
        self._point_fit_source_box = None
        self._point_fit_pointer = None
        self._point_fit_global_pointer = None
        self._point_fit_lock_click = False
        if not keep_lock:
            self._point_fit_locked_corner = None
            self._point_fit_locked_target = None
            self._point_fit_locked_box = None
            self._point_fit_round_locks = False
        if keep_press:
            if self._point_fit_pressed:
                self._point_fit_release_pending = True
            self._point_fit_pressed = False
        else:
            self._point_fit_pressed = False
            self._point_fit_release_pending = False
        self.update()

    def _point_fit_end_round(
        self,
        keep_press: bool = False,
        *,
        shift_released: bool = False,
        keep_lock: bool = False,
        finish: bool = False,
    ) -> None:
        """Clear the fit and remember a finished round until Shift up.

        ``keep_lock`` keeps the corner and leaves the round running, so a
        retrying click still gets its preview without a new Shift press.
        ``finish`` marks a committed round as finished whatever entry it
        used: a held Shift then only selects rectangles, and fitting waits
        for the next real Shift press.
        """
        if keep_lock:
            self._clear_point_fit(keep_press=keep_press, keep_lock=True)
            return
        if shift_released:
            self._point_fit_entry = None
            self._point_fit_round_spent = False
        elif finish or self._point_fit_entry == ENTRY_LOCK:
            self._point_fit_entry = ENTRY_FINISHED
        elif self._point_fit_entry != ENTRY_FINISHED:
            self._point_fit_entry = None
        self._clear_point_fit(keep_press=keep_press, keep_lock=keep_lock)

    def _point_fit_cancel_during_release(self) -> None:
        """Cancel from inside the release that ended the gesture.

        That release is already being consumed by the caller, so nothing is
        still owed: marking a pending release here would leave the fit
        waiting for a second one that never arrives.
        """
        self._point_fit_end_round()
        self._point_fit_release_pending = False
        self._point_fit_round_spent = True

    def _point_fit_cancel_round(self) -> None:
        """Cancel the round and consume any release its gesture still owns.

        The Shift press that opened the round is spent by the cancel: later
        mouse events must not restart fitting on a key the user never
        pressed again. Only a new real Shift press clears the block.
        """
        self._point_fit_end_round(
            keep_press=self._point_fit_release_pending
            or self._point_fit_pressed
        )
        self._point_fit_round_spent = True

    def _point_fit_left_press_owned(self) -> bool:
        """Return whether an active or cancelled gesture owns the press.

        A cancelled locked fit gives up the active press but keeps the
        release it is still owed, so clearing a round has to preserve either
        state instead of dropping the ownership.
        """
        return bool(self._point_fit_pressed or self._point_fit_release_pending)

    def _point_fit_mouse_buttons(self) -> Qt.MouseButton:
        """Return the buttons the window system reports as held right now."""
        return QtGui.QGuiApplication.mouseButtons()

    def _point_fit_abandon_pending_release(self) -> None:
        """Drop a release that never arrived before a new left press.

        The fit owns a cancelled press only until that press is released. A
        new left press proves the old one is over, so the stale ownership
        must not swallow the new gesture.
        """
        if not self._point_fit_release_pending:
            return
        self._point_fit_release_pending = False
        self._point_fit_pressed = False

    def _point_fit_ensure_entry(self) -> str | None:
        """Resolve Shift input when the canvas missed the initial key press.

        This degraded entry only keeps the classic hover preview: locking a
        corner belongs to a round a real Shift press opened.
        """
        if self._point_fit_entry == ENTRY_FINISHED:
            return None
        if self._point_fit_entry is not None:
            return self._point_fit_entry
        if self._point_fit_round_spent:
            # The still-held Shift already belonged to a cancelled round.
            return None
        if self._point_fit_selected_rectangle() is None:
            return None
        self._point_fit_entry = ENTRY_NATIVE
        self._point_fit_round_locks = False
        return ENTRY_NATIVE

    def _point_fit_shift_round(self, modifiers: Qt.KeyboardModifier) -> bool:
        """Record how this Shift round started and show its first preview.

        Pressing Shift inside the rectangle locks a corner immediately. An
        outside or outline press starts the classic click fit; that entry
        then locks the first clear inside zone the pointer reaches.

        Waiting for the release of a cancelled gesture never takes over this
        press: the cancelled gesture no longer drives it, so a real Shift
        press starts a new round from the current cursor position. Only a
        button Qt still reports as held keeps a new lock away, because those
        moves still belong to the cancelled drag.
        """
        if not modifiers & Qt.KeyboardModifier.ShiftModifier:
            return False
        if self._point_fit_pressed:
            return self._point_fit_refresh_from_cursor(modifiers)
        if (
            self.is_loading
            or self._space_pressed
            or self._right_pan_start is not None
            or self._rectangle_edge_drag is not None
            or self._point_fit_mouse_buttons()
        ):
            return False
        if self._pointer_down:
            if not self._point_fit_release_pending:
                return False
            # The cancelled gesture never saw its release, so the flag is
            # stale and must not outlive the press it described.
            self._pointer_down = False
        local = self.mapFromGlobal(QtGui.QCursor.pos())
        shape = self._point_fit_selected_rectangle()
        pos = None
        inside = False
        if shape is not None and self.rect().contains(local):
            pos = self.transform_pos(QtCore.QPointF(local))
            inside = point_fit_inside_box(
                self._point_fit_shape_box(shape), (pos.x(), pos.y())
            )
        self._point_fit_entry = None
        self._clear_point_fit(keep_press=self._point_fit_left_press_owned())
        # A real key press is exactly what may restart fitting.
        self._point_fit_round_spent = False
        if shape is None:
            return False
        # Only a round opened by this real key press may lock a corner.
        self._point_fit_round_locks = True
        if not inside or pos is None:
            self._point_fit_entry = ENTRY_NATIVE
            if pos is None:
                return True
        else:
            self._point_fit_entry = ENTRY_LOCK
            self._point_fit_locked_target = shape
            self._point_fit_locked_box = self._point_fit_shape_box(shape)
        handled = self._point_fit_move(
            pos, modifiers | Qt.KeyboardModifier.ShiftModifier
        )
        if handled and self._rectangle_edge_hover is not None:
            self._rectangle_edge_cancel()
        return True

    def _point_fit_selected_rectangle(self) -> Shape | None:
        """Return the one visible, unlocked rectangle eligible for fitting."""
        if (
            not self.editing()
            or self.is_auto_labeling
            or self.is_brush_mode
            or self.is_magic_wand_mode
            or not self._has_valid_pixmap()
            or len(self.selected_shapes) != 1
        ):
            return None
        shape = self.selected_shapes[0]
        if (
            shape not in self.shapes
            or shape.shape_type != "rectangle"
            or shape.locked
            or not shape.visible
            or not self.is_visible(shape)
            or len(shape.points) != 4
        ):
            return None
        return shape

    @staticmethod
    def _point_fit_shape_box(
        shape: Shape,
    ) -> tuple[float, float, float, float]:
        """Return the image-coordinate bounds of a rectangle."""
        xs = [point.x() for point in shape.points]
        ys = [point.y() for point in shape.points]
        return min(xs), min(ys), max(xs), max(ys)

    def _point_fit_valid_box(
        self, box: tuple[float, float, float, float]
    ) -> bool:
        """Validate clipped proposals using the canvas image extent."""
        left, top, right, bottom = box
        return (
            all(math.isfinite(value) for value in box)
            and right - left >= 1
            and bottom - top >= 1
            and 0 <= left <= right <= self.pixmap.width()
            and 0 <= top <= bottom <= self.pixmap.height()
        )

    def _point_fit_clamp_box(
        self, box: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float] | None:
        """Clip a proposal before checking its remaining image area."""
        if not all(math.isfinite(value) for value in box):
            return None
        left, top, right, bottom = box
        width, height = self.pixmap.width(), self.pixmap.height()
        clipped = (
            max(0.0, min(left, width)),
            max(0.0, min(top, height)),
            max(0.0, min(right, width)),
            max(0.0, min(bottom, height)),
        )
        return clipped if self._point_fit_valid_box(clipped) else None

    def _point_fit_remapped_pointer(self) -> QtCore.QPointF | None:
        """Return a new image position if navigation moved the image."""
        global_pos = self._point_fit_global_pointer
        if global_pos is None:
            return None
        origin = self.mapToGlobal(QtCore.QPoint())
        pos = self.transform_pos(global_pos - QtCore.QPointF(origin))
        # Compare raw image positions so a clipped preview at the boundary
        # can be reused on subsequent paints.
        return pos if pos != self._point_fit_pointer else None

    def _point_fit_set_preview_pointer(
        self, pos: QtCore.QPointF, hint: str, *, request_update: bool
    ) -> None:
        """Store the raw landing point and its clipped display position."""
        self._point_fit_pointer = QtCore.QPointF(pos)
        self._point_fit_cursor = QtCore.QPointF(
            *self._point_fit_clip_point((pos.x(), pos.y()))
        )
        self.setToolTip(hint)
        if request_update:
            local = (pos + self.offset_to_center()) * self.scale
            origin = self.mapToGlobal(QtCore.QPoint())
            self._point_fit_global_pointer = local + QtCore.QPointF(origin)
            self.update()

    def _point_fit_clip_point(
        self, point: tuple[float, float]
    ) -> tuple[float, float]:
        """Clip one image-coordinate point to the visible image extent."""
        width, height = self.pixmap.width(), self.pixmap.height()
        return (
            max(0.0, min(point[0], width)),
            max(0.0, min(point[1], height)),
        )

    def _point_fit_candidate_source_changed(self, target: Shape) -> bool:
        """Return whether the candidate no longer matches its source."""
        return (
            self._point_fit_source_target is not target
            or self._point_fit_source_box is None
            or self._point_fit_shape_box(target) != self._point_fit_source_box
        )

    def _point_fit_capture_matches(self, target: Shape | None) -> bool:
        """Check the selected rectangle against the press-time geometry."""
        return (
            target is not None
            and target is self._point_fit_target
            and tuple((p.x(), p.y()) for p in target.points)
            == self._point_fit_start
        )

    def _point_fit_lock_target(self) -> Shape | None:
        """Return the original target while its selection and bounds match."""
        target = self._point_fit_locked_target
        box = self._point_fit_locked_box
        if (
            target is not None
            and self._point_fit_selected_rectangle() is target
            and self._point_fit_shape_box(target) == box
        ):
            return target
        return None

    def _point_fit_lock_visible(self) -> bool:
        """Return whether this frame shows the locked-corner flow.

        A round that kept its corner after an accepted click interrupts the
        normal flow: only Shift being released again ends it.
        """
        return bool(
            self._point_fit_locked_target is not None
            and self._point_fit_locked_corner is not None
            and self._point_fit_locked_box is not None
            and self._point_fit_entry in (ENTRY_LOCK, ENTRY_FINISHED)
            and (not self._point_fit_pressed or self._point_fit_lock_click)
        )

    def _point_fit_clear_classic_preview(self) -> None:
        """Drop the hover candidate while keeping the locked corner."""
        if self._point_fit_cursor is not None:
            self.setToolTip("")
        self._point_fit_pending_box = None
        self._point_fit_cursor = None
        self._point_fit_anchor = None
        self._point_fit_source_target = None
        self._point_fit_source_box = None
        self._point_fit_pointer = None
        self._point_fit_global_pointer = None

    def _point_fit_update_lock_preview(
        self, pos: QtCore.QPointF, *, request_update: bool = True
    ) -> None:
        """Preview the rectangle spanned by the saved corner and cursor."""
        box = self._point_fit_locked_box
        corner = self._point_fit_locked_corner
        if box is None or corner is None:
            return
        point = (pos.x(), pos.y())
        proposal = self._point_fit_clamp_box(
            proposed_inward_point_fit_box(box, corner, point)
        )
        self._point_fit_target = self._point_fit_locked_target
        self._point_fit_pending_box = proposal
        self._point_fit_anchor = self._point_fit_clip_point(
            corner_point(box, corner)
        )
        hint = ""
        if proposal is None:
            hint = QtCore.QCoreApplication.translate(
                "Canvas", "Rectangle is outside the image or too small."
            )
        self._point_fit_set_preview_pointer(
            pos, hint, request_update=request_update
        )

    def _update_point_fit(
        self,
        shape: Shape,
        pos: QtCore.QPointF,
        *,
        request_update: bool = True,
    ) -> None:
        """Calculate a non-mutating hover preview for the selected box."""
        box = (
            self._point_fit_box
            if self._point_fit_pressed and self._point_fit_box is not None
            else self._point_fit_shape_box(shape)
        )
        point = (pos.x(), pos.y())
        corner = (
            self._point_fit_corner
            if self._point_fit_pressed
            else point_fit_decision(
                box,
                point,
                self.scale,
                previous_corner=(
                    self._point_fit_hover_corner
                    if not self._point_fit_candidate_source_changed(shape)
                    else None
                ),
            ).edge
        )
        if not self._point_fit_pressed:
            self._point_fit_hover_corner = corner
        if corner is None:
            proposal = None
            anchor = None
        else:
            proposal = proposed_point_fit_box(box, corner, point)
            anchor = corner_point(box, OPPOSITE_CORNER[corner])
        # Record the source of this candidate: the same target with different
        # coordinates or a different target invalidates it.
        self._point_fit_source_target = shape
        self._point_fit_source_box = box
        self._point_fit_target = shape
        self._point_fit_anchor = (
            self._point_fit_clip_point(anchor) if anchor is not None else None
        )
        self._point_fit_pending_box = (
            self._point_fit_clamp_box(proposal)
            if proposal is not None
            else None
        )
        if corner is None:
            hint = QtCore.QCoreApplication.translate(
                "Canvas", "Unable to infer corner."
            )
        elif self._point_fit_pending_box is None:
            hint = QtCore.QCoreApplication.translate(
                "Canvas", "Rectangle is outside the image or too small."
            )
        else:
            hint = ""
        self._point_fit_set_preview_pointer(
            pos, hint, request_update=request_update
        )

    def _point_fit_lock_move(self, pos: QtCore.QPointF) -> bool:
        """Choose the fixed corner once, then update the same preview."""
        shape = self._point_fit_lock_target()
        box = self._point_fit_locked_box
        if shape is None or box is None:
            pressed = self._point_fit_pressed
            self._point_fit_end_round(
                keep_press=self._point_fit_left_press_owned()
            )
            return pressed
        if self._point_fit_pressed:
            if self._point_fit_lock_click:
                self._point_fit_update_lock_preview(pos)
            else:
                self._update_point_fit(shape, pos)
            return True
        if self._point_fit_locked_corner is None:
            decision = point_fit_lock_decision(
                box, (pos.x(), pos.y()), self.scale
            )
            if decision.edge is not None:
                self._point_fit_locked_corner = OPPOSITE_CORNER[decision.edge]
        self._point_fit_update_lock_preview(pos)
        return True

    def _point_fit_native_move(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Preview the click fit and lock the first clear inside zone.

        A round that started outside or on the outline keeps the original
        preview until the pointer enters an unambiguous inside quadrant.
        From that moment the locked corner replaces the inferred one, so the
        pending reveal stops re-choosing a fixed point.
        """
        shape = self._point_fit_selected_rectangle()
        if self._point_fit_pressed and not self._point_fit_capture_matches(
            shape
        ):
            self._point_fit_cancel_round()
            return True
        if shape is None:
            self._clear_point_fit(
                keep_press=self._point_fit_left_press_owned()
            )
            return False
        self._update_point_fit(shape, pos)
        if self._point_fit_pressed:
            return True
        if not self._point_fit_round_locks:
            # A synthesised entry has no Shift press behind it, so the hover
            # keeps re-inferring its corner instead of locking one.
            return True
        box = self._point_fit_shape_box(shape)
        decision = point_fit_lock_decision(box, (pos.x(), pos.y()), self.scale)
        if decision.edge is None:
            return True
        self._point_fit_entry = ENTRY_LOCK
        self._point_fit_locked_target = shape
        self._point_fit_locked_box = box
        self._point_fit_locked_corner = OPPOSITE_CORNER[decision.edge]
        self._point_fit_update_lock_preview(pos)
        return True

    def _point_fit_move(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Preview a fit or consume a cancelled in-progress gesture."""
        if self._point_fit_release_pending and self._point_fit_entry is None:
            # Nothing has started a round yet, so no Shift-modified move may
            # take the cancelled gesture back. A real Shift press sets the
            # entry and may then preview while the old release is still owed.
            return False
        if not modifiers & Qt.KeyboardModifier.ShiftModifier:
            if self._point_fit_pressed:
                self._point_fit_end_round(keep_press=True, shift_released=True)
                return True
            if (
                self._point_fit_cursor is not None
                or self._point_fit_locked_target is not None
            ):
                self._point_fit_end_round(
                    keep_press=self._point_fit_left_press_owned(),
                    shift_released=True,
                )
            self._point_fit_entry = None
            return False
        if self._point_fit_ensure_entry() is None:
            return False
        if self._point_fit_entry == ENTRY_LOCK:
            return self._point_fit_lock_move(pos)
        return self._point_fit_native_move(pos, modifiers)

    def _point_fit_refresh_from_cursor(
        self, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Refresh modifier-only changes without waiting for a mouse move."""
        if (
            self.is_loading
            or self._space_pressed
            or self._right_pan_start is not None
            or self._rectangle_edge_drag is not None
            or (
                (self._pointer_down or self._point_fit_mouse_buttons())
                and not self._point_fit_pressed
            )
        ):
            return False
        local = self.mapFromGlobal(QtGui.QCursor.pos())
        if not self.rect().contains(local):
            if not self._point_fit_pressed and (
                self._point_fit_locked_target is None
            ):
                # Leaving the canvas only drops the preview; a release the
                # cancelled gesture is still owed must stay with the fit.
                self._clear_point_fit(
                    keep_press=self._point_fit_left_press_owned()
                )
            return False
        handled = self._point_fit_move(
            self.transform_pos(QtCore.QPointF(local)), modifiers
        )
        if handled and self._rectangle_edge_hover is not None:
            self._rectangle_edge_cancel()
        return handled

    def _point_fit_press_classic(
        self, shape: Shape, pos: QtCore.QPointF
    ) -> bool:
        """Capture the classic single-click fit gesture."""
        # A press can arrive at a different position than the last delivered
        # move, without any intermediate move event. Keep the anchor the user
        # actually saw: recompute only when the shown candidate is stale.
        shown = (
            self._point_fit_pending_box is not None
            and self._point_fit_target is shape
            and not self._point_fit_candidate_source_changed(shape)
        )
        if not shown:
            self._update_point_fit(shape, pos)
        proposal = self._point_fit_pending_box
        if proposal is None or proposal == self._point_fit_shape_box(shape):
            # Nothing to commit: either no valid candidate or one identical
            # to the current geometry, which draws no dashed preview. Hand
            # this whole press back to the native canvas. Only the transient
            # preview is dropped; the inside-lock eligibility a real Shift
            # press created survives, so moving into a clear zone after the
            # release still locks.
            self._point_fit_clear_classic_preview()
            return False
        self._point_fit_box = self._point_fit_shape_box(shape)
        # Capture exactly the corner used by the visible, stabilised preview.
        self._point_fit_corner = self._point_fit_hover_corner
        self._point_fit_pressed = True
        self._point_fit_start = tuple((p.x(), p.y()) for p in shape.points)
        if shown:
            self._update_point_fit(shape, pos)
        return True

    def _point_fit_start_lock_click(self, pos: QtCore.QPointF) -> None:
        """Capture the confirming click, even outside the original box."""
        self._point_fit_pressed = True
        self._point_fit_lock_click = True
        self._point_fit_update_lock_preview(pos)

    def _point_fit_press(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Capture one Shift-left gesture when a valid target is selected."""
        if not modifiers & Qt.KeyboardModifier.ShiftModifier:
            return False
        entry = self._point_fit_ensure_entry()
        if entry is None:
            return False
        if entry == ENTRY_LOCK:
            shape = self._point_fit_lock_target()
            if shape is not None and self._point_fit_locked_corner is not None:
                self._point_fit_start_lock_click(pos)
                return True
            # A press before the corner is fixed belongs to the canvas.
            self._point_fit_end_round()
            return False
        shape = self._point_fit_selected_rectangle()
        if shape is None:
            return False
        return self._point_fit_press_classic(shape, pos)

    def _point_fit_commit(
        self,
        shape: Shape,
        proposal: tuple[float, float, float, float],
    ) -> None:
        """Write one geometry change and record it as one undo step."""
        current = [item.to_dict() for item in self.shapes]
        if (
            not self.shapes_backups
            or [item.to_dict() for item in self.shapes_backups[-1]] != current
        ):
            self.store_shapes()
        left, top, right, bottom = proposal
        shape.points = [
            QtCore.QPointF(left, top),
            QtCore.QPointF(right, top),
            QtCore.QPointF(right, bottom),
            QtCore.QPointF(left, bottom),
        ]
        self.store_shapes()
        self.shape_moved.emit()

    def _point_fit_release_lock(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> None:
        """Confirm the locked preview at the release position.

        An unchanged release only ends the click. An invalid release does
        the same and keeps the locked corner so the next click can retry.
        Losing Shift or the original target during the click cancels the
        round instead: the marker and the retry belong to a live round.
        """
        shape = self._point_fit_lock_target()
        box = self._point_fit_locked_box
        self._point_fit_lock_click = False
        if (
            modifiers & Qt.KeyboardModifier.ShiftModifier
            and shape is not None
            and self._point_fit_locked_corner is not None
        ):
            self._point_fit_update_lock_preview(pos)
            proposal = self._point_fit_pending_box
            if proposal is not None and proposal != box:
                self._point_fit_commit(shape, proposal)
                self._point_fit_end_round()
                self.deselect_shape()
                return
            self._point_fit_end_round(keep_lock=True)
            return
        self._point_fit_cancel_during_release()

    def _point_fit_release(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Commit one valid fit and record it as one undoable operation."""
        if not self._point_fit_pressed:
            return False
        if self._point_fit_lock_click:
            self._point_fit_release_lock(pos, modifiers)
            return True
        shape = self._point_fit_target
        valid = (
            bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            and shape is not None
            and self._point_fit_capture_matches(
                self._point_fit_selected_rectangle()
            )
        )
        if not valid:
            # Shift is gone or the original geometry changed: this release
            # is the cancel's own event, so it must not leave a debt behind.
            self._point_fit_cancel_during_release()
            return True
        self._update_point_fit(shape, pos)
        proposal = self._point_fit_pending_box
        changed = (
            proposal is not None
            and proposal != self._point_fit_shape_box(shape)
        )
        if changed:
            self._point_fit_commit(shape, proposal)
        # A committed round is over whatever entry produced it: a held Shift
        # may still select rectangles, but only a new Shift press refits.
        self._point_fit_end_round(finish=changed, keep_lock=not changed)
        if changed:
            self.deselect_shape()
        return True

    def _point_fit_handle_release_event(
        self, event: QtGui.QMouseEvent
    ) -> bool:
        """Consume the mouse release belonging to a point-fit gesture.

        A release still owed to a cancelled gesture is consumed first and
        only ends that ownership: it never commits geometry or resolves a
        round that a later Shift press already started.
        """
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self._point_fit_release_pending:
            self._point_fit_release_pending = False
            event.accept()
            return True
        if not self._point_fit_pressed:
            return False
        if self.is_loading:
            # The image is being replaced: consume the click instead of
            # committing it against the annotations that are going away.
            self._point_fit_cancel_during_release()
            event.accept()
            return True
        if not self._point_fit_release(
            self.transform_pos(event.position()), event.modifiers()
        ):
            return False
        event.accept()
        return True

    def _build_lock_point_fit_preview(self) -> PointFitPreview | None:
        """Snapshot the fixed corner and its live candidate.

        The marker is derived from the locked original box and corner name,
        not from the transient hover candidate. An accepted click clears
        that candidate, yet the corner stays locked for a retry, so the solid
        point must keep showing while the pointer sits still.
        """
        target = self._point_fit_lock_target()
        box = self._point_fit_locked_box
        if target is None or box is None:
            self._point_fit_end_round(
                keep_press=self._point_fit_left_press_owned()
            )
            return None
        corner = self._point_fit_locked_corner
        if corner is None:
            return None
        fixed = self._point_fit_clip_point(corner_point(box, corner))
        pos = self._point_fit_remapped_pointer()
        if pos is not None:
            self._point_fit_update_lock_preview(pos, request_update=False)
        pointer = self._point_fit_cursor
        candidate = self._point_fit_pending_box
        outline_path = None
        if candidate is not None and candidate != box:
            outline_path = build_remaining_outline(
                box, candidate, scale=self.scale
            )
        return PointFitPreview(
            target=target,
            box=box,
            candidate_box=candidate,
            outline_path=outline_path,
            fixed_point=fixed,
            pointer=(
                (pointer.x(), pointer.y()) if pointer is not None else None
            ),
            guides=pointer is not None,
        )

    def _build_point_fit_preview(self) -> PointFitPreview | None:
        """Snapshot the fit target, candidate, and shared-edge outline.

        The pending candidate is only reused while its recorded source target
        and original geometry still match the rectangle. A hover preview is
        recomputed from the current geometry and the recorded pointer before
        this snapshot; a captured gesture whose geometry changed elsewhere is
        cancelled and its release stays consumed.
        """
        if self._point_fit_lock_visible():
            return self._build_lock_point_fit_preview()
        if self._point_fit_cursor is None:
            return None
        target = self._point_fit_selected_rectangle()
        if self._point_fit_pressed and not self._point_fit_capture_matches(
            target
        ):
            self._point_fit_cancel_round()
            return None
        if target is not self._point_fit_target:
            target = None
        if target is not None:
            pos = self._point_fit_remapped_pointer()
            if pos is None and self._point_fit_candidate_source_changed(
                target
            ):
                pos = self._point_fit_pointer
            if pos is not None:
                self._update_point_fit(target, pos, request_update=False)
        box = (
            rectangle_box_from_points(target.points)
            if target is not None
            else None
        )
        candidate = self._point_fit_pending_box if box is not None else None
        outline_path = None
        if candidate is not None and candidate != box:
            outline_path = build_remaining_outline(
                box, candidate, scale=self.scale
            )
        # Only a locked corner paints the solid original point; the click fit
        # keeps its candidate hinge implicit so hover never looks locked.
        pointer = self._point_fit_cursor
        return PointFitPreview(
            target=target if box is not None else None,
            box=box,
            candidate_box=candidate,
            outline_path=outline_path,
            fixed_point=None,
            pointer=(
                (pointer.x(), pointer.y()) if pointer is not None else None
            ),
        )

    def _paint_point_fit(self, painter: QtGui.QPainter) -> None:
        """Draw the pending rectangle, its fixed corner, and the point."""
        preview = self._point_fit_preview
        if preview is None:
            return
        painter.save()
        marker_color = QtGui.QColor(FIT_CANDIDATE_COLOR)
        color = (
            marker_color
            if preview.valid
            else QtGui.QColor(INVALID_CANDIDATE_COLOR)
        )
        pen = QtGui.QPen(color)
        pen.setCosmetic(True)
        pen.setWidthF(FIT_CANDIDATE_WIDTH)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if preview.owns_guides:
            guide_pen = QtGui.QPen(marker_color)
            guide_pen.setCosmetic(True)
            guide_pen.setWidthF(1.0)
            guide_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            width = float(self.pixmap.width())
            height = float(self.pixmap.height())
            guide_x, guide_y = preview.pointer
            painter.drawLine(
                QtCore.QPointF(guide_x, 0.0),
                QtCore.QPointF(guide_x, height),
            )
            painter.drawLine(
                QtCore.QPointF(0.0, guide_y),
                QtCore.QPointF(width, guide_y),
            )
            painter.setPen(pen)
        if preview.candidate_differs:
            left, top, right, bottom = preview.candidate_box
            candidate_path = QtGui.QPainterPath()
            candidate_path.addRect(
                QtCore.QRectF(left, top, right - left, bottom - top)
            )
            painter.drawPath(candidate_path)
        if preview.fixed_point is not None:
            marker_pen = QtGui.QPen(marker_color)
            marker_pen.setCosmetic(True)
            marker_pen.setWidthF(FIT_CANDIDATE_WIDTH)
            painter.setPen(marker_pen)
            painter.setBrush(marker_color)
            painter.drawEllipse(
                QtCore.QPointF(*preview.fixed_point),
                3 / self.scale,
                3 / self.scale,
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
        if preview.pointer is not None:
            painter.drawEllipse(
                QtCore.QPointF(*preview.pointer),
                4 / self.scale,
                4 / self.scale,
            )
        painter.restore()
