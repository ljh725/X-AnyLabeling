"""Monotonic, mutually exclusive work intervals for a single visit to a round."""

import time
import uuid


class WorkClock:
    """Call tick at one-second intervals. No wall clock or input frequency estimate."""

    def __init__(self, idle_seconds=120, *, clock=time.monotonic, max_gap=5):
        self.clock = clock
        self.idle_seconds = max(1.0, float(idle_seconds))
        self.max_gap = float(max_gap)
        self.round_id = None
        self.session_id = None
        self.paused = False
        self.foreground = True
        self.suspended = False
        self.ready = True
        self.blocked = False
        self.completed = False
        self._reset(self.clock())

    def _reset(self, now):
        self._last = self._start = now
        self._seconds = dict.fromkeys(
            ("working", "paused", "inactive", "not_ready", "blocking_wait"),
            0.0,
        )
        self._pending = self._excluded = self._gap = self._streak = 0.0
        self._segments = []
        self._adjustments = []
        self._gaps = []

    @property
    def state(self):
        if self.round_id is None or self.completed:
            return "closed"
        if self.paused:
            return "paused"
        if self.suspended or not self.foreground:
            return "inactive"
        if self.blocked:
            return "blocking_wait"
        return "working" if self.ready else "not_ready"

    def attach(self, round_id, *, ready=True, completed=False):
        self._reset(self.clock())
        self.round_id = round_id
        self.session_id = uuid.uuid4().hex if round_id else None
        self.ready = ready
        self.completed = completed

    def tick(self):
        now = self.clock()
        if now <= self._last:
            return
        previous, self._last = self._last, now
        duration = now - previous
        state = self.state
        if state == "closed":
            return
        start, end = previous - self._start, now - self._start
        if duration > self.max_gap:
            self._gaps.append((start, end))
            self._gap += duration
            self._streak = 0.0
            return
        self._seconds[state] += duration
        if self._segments and self._segments[-1][:2] == (state, start):
            # Tuples hold (state, end, start) so adjacent intervals coalesce.
            self._segments[-1] = (state, end, self._segments[-1][2])
        else:
            self._segments.append((state, end, start))
        if state == "working":
            old_streak = self._streak
            self._streak += duration
            if old_streak >= self.idle_seconds:
                self._pending += duration
            elif self._streak >= self.idle_seconds:
                self._pending += self._streak

    def change(self, **flags):
        """Charge elapsed time to the old state before applying new conditions."""
        before = self.state
        self.tick()
        for key, value in flags.items():
            setattr(self, key, bool(value))
        if self.state != before:
            self._streak = 0.0

    def activity(self):
        if self.state != "working":
            return
        self.tick()
        self._streak = 0.0

    def confirm_idle(self, exclude):
        self.tick()
        amount = self._pending
        if amount:
            self._adjustments.append(
                {
                    "at": self._last - self._start,
                    "decision": "exclude" if exclude else "reviewed",
                    "seconds": amount,
                }
            )
            if exclude:
                self._excluded += amount
            self._pending = self._streak = 0.0
        return amount

    @property
    def totals(self):
        return {
            **self._seconds,
            "pending_idle": self._pending,
            "excluded_idle": self._excluded,
            "adjusted_working": self._seconds["working"] - self._excluded,
            "timing_gap_seconds": self._gap,
        }

    @property
    def audit(self):
        return {
            "segments": [
                (state, start, end) for state, end, start in self._segments
            ],
            "adjustments": [item.copy() for item in self._adjustments],
            "gaps": list(self._gaps),
        }
