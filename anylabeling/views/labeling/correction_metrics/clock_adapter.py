"""Collect application work intervals only while correction statistics are enabled."""

import ctypes
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from anylabeling.services.correction_metrics.timing import WorkClock


class _WindowsSessionEvents(QAbstractNativeEventFilter):
    """Receive Windows session and power broadcasts for the labeling window."""

    def __init__(self, host, changed):
        super().__init__()
        from ctypes import wintypes

        self.hwnd = int(host.window().winId())
        self.message_type = wintypes.MSG
        self.changed = changed
        self.locked = self.asleep = False
        self.wts = ctypes.windll.wtsapi32
        self.registered = self.wts.WTSRegisterSessionNotification(
            ctypes.c_void_p(self.hwnd), 0
        )

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = self.message_type.from_address(int(message))
            if msg.hwnd == self.hwnd:
                if msg.message == 0x02B1 and msg.wParam in (7, 8):
                    self.locked = msg.wParam == 7
                    self.changed(self.locked or self.asleep)
                elif msg.message == 0x0218 and msg.wParam in (4, 7, 18):
                    self.asleep = msg.wParam == 4
                    self.changed(self.locked or self.asleep)
        return False, 0

    def close(self):
        if self.registered:
            self.wts.WTSUnRegisterSessionNotification(ctypes.c_void_p(self.hwnd))


class QtClockAdapter(QObject):
    """Checkpoint absolute per-session totals through callback(round, session, totals, closed)."""

    def __init__(self, host, callback, idle_seconds=120):
        super().__init__(host)
        self.host = host
        self.callback = callback
        self.work = WorkClock(idle_seconds)
        self.app = QApplication.instance()
        self._explicit_block = False
        self._native = None
        self._stopped = False
        self.app.installEventFilter(self)
        self.app.applicationStateChanged.connect(self._sync_foreground)
        if sys.platform == "win32" and self.app.platformName() == "windows":
            self._native = _WindowsSessionEvents(host, self._system_suspended)
            self.app.installNativeEventFilter(self._native)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
        self.heartbeat.timeout.connect(self._heartbeat)
        self.heartbeat.start()
        self._sync_foreground()

    @property
    def state(self):
        return self.work.state

    @property
    def totals(self):
        return self.work.totals

    @property
    def audit(self):
        return self.work.audit

    @property
    def session_id(self):
        return self.work.session_id

    @property
    def pending_idle_seconds(self):
        return self.totals["pending_idle"]

    def _checkpoint(self, closed=False):
        if self.work.round_id:
            self.callback(
                self.work.round_id, self.session_id, self.totals, closed
            )

    def _heartbeat(self):
        self._sync_foreground()
        self.work.change(blocked=self._is_blocked())
        if self.state != "closed":
            self._checkpoint()

    def _sync_foreground(self, *_args):
        active = self.app.activeWindow()
        related = active is not None and (
            active == self.host.window() or self.host.window().isAncestorOf(active)
        )
        # A modal dialog belonging to this window (label dialog, save prompt,
        # error message) is still annotation work: Qt's static dialog helpers
        # create a separate top-level window, so comparing activeWindow() alone
        # would stop the clock in the middle of a correction.
        modal = self.app.activeModalWidget()
        modal_work = False
        if modal is not None:
            try:
                owner = modal.parentWidget()
                modal_work = (
                    owner is None
                    or owner is self.host
                    or owner.window() is self.host.window()
                )
            except (AttributeError, RuntimeError):
                modal_work = False
        self.work.change(
            foreground=(
                self.app.applicationState() == Qt.ApplicationState.ApplicationActive
                and (related or modal_work)
            )
        )

    def _system_suspended(self, value):
        self.work.change(suspended=value)
        self._checkpoint()

    def _is_blocked(self):
        return self._explicit_block or getattr(
            self.host, "_batch_processing_active", False
        )

    def eventFilter(self, obj, event):
        if self._stopped:
            return False
        kind = event.type()
        if kind in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate):
            self._sync_foreground()
        elif kind in (
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
        ) and isinstance(obj, QWidget):
            if obj.window() == self.host.window() or self.host.window().isAncestorOf(obj):
                self.work.activity()
        return False

    def scope(self, round_id, *, completed=False, ready=True):
        if round_id == self.work.round_id:
            self.work.change(completed=completed, ready=ready)
            return
        self.work.tick()
        self._checkpoint(closed=True)
        self.work.attach(round_id, completed=completed, ready=ready)
        self.work.change(blocked=self._is_blocked())
        self._sync_foreground()
        if not completed:
            self._checkpoint()

    def set_ready(self, value):
        self.work.change(ready=value)

    def set_paused(self, value):
        self.work.change(paused=value)
        self._checkpoint()

    def set_blocked(self, value):
        self._explicit_block = bool(value)
        self.work.change(blocked=self._is_blocked())

    def set_completed(self, value):
        self.work.change(completed=value)
        self._checkpoint(closed=bool(value))

    def confirm_idle(self, exclude):
        seconds = self.work.confirm_idle(exclude)
        if seconds:
            self._checkpoint()
        return seconds

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self.heartbeat.stop()
        self.work.tick()
        self._checkpoint(closed=True)
        self.work.attach(None)
        self.app.removeEventFilter(self)
        self.app.applicationStateChanged.disconnect(self._sync_foreground)
        if self._native:
            self.app.removeNativeEventFilter(self._native)
            self._native.close()
            self._native = None
