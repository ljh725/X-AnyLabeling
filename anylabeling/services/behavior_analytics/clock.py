"""Clock readings for ordering events and calculating durations."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ClockReading:
    """A wall-clock locator plus a monotonic duration source."""

    occurred_at_utc: str
    local_date: str
    timezone_offset: str
    monotonic_ms: int


class SystemClock:
    """Read UTC/local time and monotonic time from the current process."""

    def read(self) -> ClockReading:
        """Return one internally consistent clock reading."""
        utc_now = datetime.now(timezone.utc)
        local_now = utc_now.astimezone()
        return ClockReading(
            occurred_at_utc=utc_now.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            local_date=local_now.date().isoformat(),
            timezone_offset=local_now.strftime("%z")[:3]
            + ":"
            + local_now.strftime("%z")[3:],
            monotonic_ms=time.monotonic_ns() // 1_000_000,
        )
