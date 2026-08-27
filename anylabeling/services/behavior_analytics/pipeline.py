"""Range, streaming and first-stage quality helpers for behavior analytics.

The module deliberately contains no Qt dependencies.  It is the shared
boundary between local hourly recording and the deterministic export stage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator
from zoneinfo import ZoneInfo

from .catalog import validate_payload
from .schema import (
    SUPPORTED_EVENT_SCHEMA_VERSIONS,
    EventEnvelope,
    EventValidationError,
)

_HOURLY_NAME = re.compile(
    r"^events-(?P<year>\d{4})-(?P<month>\d{2})-"
    r"(?P<day>\d{2})-(?P<hour>\d{2})\.jsonl$"
)
_MONTHLY_NAME = re.compile(r"^events-(?P<year>\d{4})-(?P<month>\d{2})\.jsonl$")
_KNOWN_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_type",
        "occurred_at_utc",
        "local_date",
        "timezone_offset",
        "monotonic_ms",
        "app_session_id",
        "project_session_id",
        "project_id",
        "feature_state_version",
        "input_source",
        "result",
        "sequence_no",
        "interruption_reason",
        "image_id",
        "shape_id",
        "object_episode_id",
        "correlation_id",
        "duration_ms",
        "payload",
        "action_id",
        "action_phase",
        "started_monotonic_ms",
        "ended_monotonic_ms",
        "context_version",
        "context",
        "participating_features",
        "action_type",
        "edit_target",
        "net_change_summary",
        "selection_source",
        "selection_batch_id",
        "episode_end_reason",
        "unattributed_reason",
        "privacy_fields_removed",
        "creation_workflow_id",
        "workflow_type",
        "creation_stage",
    }
)


def parse_utc(value: str | datetime) -> datetime:
    """Parse a timestamp and return an aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def utc_text(value: datetime) -> str:
    """Serialize an aware datetime using the canonical UTC representation."""
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class UtcRange:
    """Inclusive UTC event range used by one export query."""

    start_utc: str | None = None
    end_utc: str | None = None

    def __post_init__(self) -> None:
        """Validate and canonicalize the range boundaries."""
        start = parse_utc(self.start_utc) if self.start_utc else None
        end = parse_utc(self.end_utc) if self.end_utc else None
        if start and end and start > end:
            raise ValueError("UTC range start must not be after end")
        object.__setattr__(
            self, "start_utc", utc_text(start) if start else None
        )
        object.__setattr__(self, "end_utc", utc_text(end) if end else None)

    def contains(self, occurred_at_utc: str) -> bool:
        """Return whether a timestamp is inside the inclusive range."""
        current = parse_utc(occurred_at_utc)
        if self.start_utc and current < parse_utc(self.start_utc):
            return False
        if self.end_utc and current > parse_utc(self.end_utc):
            return False
        return True

    def to_dict(self) -> dict[str, object]:
        """Return a stable manifest representation."""
        return {"start_utc": self.start_utc, "end_utc": self.end_utc}


@dataclass(frozen=True)
class RangeSelection:
    """Serializable single-range request and resolved project scope."""

    kind: str
    utc: UtcRange
    project_session_ids: frozenset[str] = frozenset()
    local_timezone: str = "UTC"
    requested_local_start: str | None = None
    requested_local_end: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return requested and resolved fields for a bundle manifest."""
        return {
            "kind": self.kind,
            "local_timezone": self.local_timezone,
            "requested_local_start": self.requested_local_start,
            "requested_local_end": self.requested_local_end,
            "resolved_utc": self.utc.to_dict(),
            "project_session_ids": sorted(self.project_session_ids),
        }


@dataclass(frozen=True)
class DualRangeSelection:
    """Two independently resolved ranges sharing one algorithm contract."""

    baseline: RangeSelection
    comparison: RangeSelection

    def __post_init__(self) -> None:
        """Reject overlapping ranges so the comparison is unambiguous."""
        left = self.baseline.utc
        right = self.comparison.utc
        left_before_right = (
            left.end_utc and right.start_utc and left.end_utc < right.start_utc
        )
        right_before_left = (
            right.end_utc and left.start_utc and right.end_utc < left.start_utc
        )
        if not left_before_right and not right_before_left:
            raise ValueError("baseline and comparison ranges must not overlap")

    def to_dict(self) -> dict[str, object]:
        """Return both range contracts."""
        return {
            "baseline": self.baseline.to_dict(),
            "comparison": self.comparison.to_dict(),
        }


def _local_to_utc(value: str | datetime, timezone_name: str) -> datetime:
    """Convert a local datetime to UTC using the requested zone."""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def build_range_selection(
    kind: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "UTC",
    local_start: str | datetime | None = None,
    local_end: str | datetime | None = None,
    active_project_session_id: str | None = None,
) -> RangeSelection:
    """Build a validated range for a preset or custom local time request.

    ``kind`` accepts ``current_project``, ``recent_1d``, ``recent_7d``,
    ``recent_30d``, ``custom`` and ``all``.  Current-project scope is rejected
    when there is no active project instead of silently widening the query.
    """
    if kind == "current_project":
        if not active_project_session_id:
            raise ValueError(
                "current project export requires an active project"
            )
        return RangeSelection(
            kind=kind,
            utc=UtcRange(),
            project_session_ids=frozenset({active_project_session_id}),
            local_timezone=timezone_name,
        )
    if kind == "all":
        return RangeSelection(
            kind=kind, utc=UtcRange(), local_timezone=timezone_name
        )
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if kind in {"recent_1d", "recent_7d", "recent_30d"}:
        days = int(kind.split("_")[1][:-1])
        return RangeSelection(
            kind=kind,
            utc=UtcRange(
                utc_text(current - timedelta(days=days)), utc_text(current)
            ),
            local_timezone=timezone_name,
        )
    if kind != "custom" or local_start is None or local_end is None:
        raise ValueError("custom range requires local_start and local_end")
    start = _local_to_utc(local_start, timezone_name)
    end = _local_to_utc(local_end, timezone_name)
    return RangeSelection(
        kind=kind,
        utc=UtcRange(utc_text(start), utc_text(end)),
        local_timezone=timezone_name,
        requested_local_start=str(local_start),
        requested_local_end=str(local_end),
    )


def parse_shard_bounds(path: str | Path) -> tuple[str, str] | None:
    """Return inclusive UTC bounds for an hourly or monthly JSONL file."""
    name = Path(path).name
    match = _HOURLY_NAME.match(name)
    if match:
        start = datetime(
            int(match["year"]),
            int(match["month"]),
            int(match["day"]),
            int(match["hour"]),
            tzinfo=timezone.utc,
        )
        return utc_text(start), utc_text(
            start + timedelta(hours=1) - timedelta(milliseconds=1)
        )
    match = _MONTHLY_NAME.match(name)
    if not match:
        return None
    year = int(match["year"])
    month = int(match["month"])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    next_month = datetime(
        year + (month == 12),
        1 if month == 12 else month + 1,
        1,
        tzinfo=timezone.utc,
    )
    return utc_text(start), utc_text(next_month - timedelta(milliseconds=1))


def _ranges_intersect(left: tuple[str, str], right: UtcRange) -> bool:
    """Return whether shard bounds intersect an inclusive UTC range."""
    if right.start_utc and left[1] < right.start_utc:
        return False
    if right.end_utc and left[0] > right.end_utc:
        return False
    return True


def candidate_event_files(
    sources: Iterable[str | Path], event_range: UtcRange | None = None
) -> list[Path]:
    """Select only possibly intersecting JSONL sources in stable order."""
    paths: set[Path] = set()
    for source in sources:
        path = Path(source)
        if path.is_file():
            paths.add(path)
        elif path.is_dir():
            paths.update(path.rglob("*.jsonl"))
    candidates = []
    for path in sorted(paths):
        bounds = parse_shard_bounds(path)
        if (
            event_range
            and bounds
            and not _ranges_intersect(bounds, event_range)
        ):
            continue
        candidates.append(path)
    return candidates


def iter_event_stream(  # noqa: C901
    sources: Iterable[str | Path],
    *,
    event_range: UtcRange | None = None,
    project_session_ids: frozenset[str] = frozenset(),
    quality: object | None = None,
    batch_size: int = 256,
    on_batch: Callable[[int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> Iterator[EventEnvelope]:
    """Yield validated events with bounded batch callbacks and cancellation.

    The optional quality object is duck-typed to avoid an import cycle with
    ``analysis.ReadQuality``.  Its counters are updated as events are read.
    """
    seen_ids: set[str] = set()
    last_sequence: dict[str, int] = {}
    batch_count = 0
    for path in candidate_event_files(sources, event_range):
        if cancel and cancel():
            return
        if (
            quality is not None
            and path.name.startswith("events-")
            and "-" in path.stem
        ):
            if path.name.endswith(".jsonl") and _HOURLY_NAME.match(path.name):
                manifest = path.with_name(f"{path.stem}.manifest.json")
                if not manifest.exists():
                    _increment_quality(quality, "manifest_error_count")
                    _increment_reason(quality, "manifest_missing")
        try:
            stream = path.open("r", encoding="utf-8")
        except OSError:
            _increment_quality(quality, "invalid_count")
            _increment_reason(quality, "file_error")
            continue
        with stream:
            for line in stream:
                if cancel and cancel():
                    return
                if not line.strip():
                    continue
                _increment_quality(quality, "read_count")
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        unknown = len(set(data) - _KNOWN_EVENT_FIELDS)
                        if quality is not None and hasattr(
                            quality, "unknown_field_count"
                        ):
                            quality.unknown_field_count += unknown
                        if (
                            data.get("schema_version")
                            not in SUPPORTED_EVENT_SCHEMA_VERSIONS
                        ):
                            _increment_quality(quality, "unknown_schema_count")
                            _increment_quality(quality, "schema_error_count")
                            _increment_reason(quality, "schema_version")
                            continue
                    event = EventEnvelope.from_mapping(data)
                    validate_payload(event.event_type, event.payload)
                except json.JSONDecodeError:
                    if not line.endswith(("\n", "\r")):
                        _increment_quality(quality, "incomplete_count")
                        _increment_reason(quality, "incomplete_tail")
                    else:
                        _increment_quality(quality, "corrupt_count")
                        _increment_reason(quality, "json_parse")
                    continue
                except EventValidationError as exc:
                    _increment_quality(quality, "invalid_count")
                    reason = _classify_validation_error(str(exc))
                    if "unsupported schema_version" in str(exc):
                        _increment_quality(quality, "unknown_schema_count")
                    _increment_quality(quality, f"{reason}_error_count")
                    _increment_reason(quality, reason)
                    continue
                except (TypeError, ValueError):
                    _increment_quality(quality, "invalid_count")
                    _increment_reason(quality, "payload_contract")
                    continue
                if event.event_id in seen_ids:
                    _increment_quality(quality, "duplicate_source_count")
                    _increment_reason(quality, "duplicate_source")
                    continue
                seen_ids.add(event.event_id)
                if event.schema_version < 3:
                    _increment_quality(quality, "legacy_ordering_count")
                if event.schema_version >= 3:
                    previous = last_sequence.get(event.app_session_id)
                    if (
                        previous is not None
                        and event.sequence_no != previous + 1
                    ):
                        if not _declares_gap(event, previous + 1):
                            _increment_quality(quality, "sequence_gap_count")
                            _increment_reason(quality, "sequence_gap")
                    last_sequence[event.app_session_id] = (
                        event.sequence_no or previous or 0
                    )
                if event_range and not event_range.contains(
                    event.occurred_at_utc
                ):
                    _increment_quality(quality, "filtered_count")
                    continue
                if (
                    project_session_ids
                    and event.project_session_id not in project_session_ids
                ):
                    _increment_quality(quality, "filtered_count")
                    continue
                _increment_quality(quality, "accepted_count")
                yield event
                batch_count += 1
                if batch_count >= max(1, batch_size):
                    if on_batch:
                        on_batch(batch_count)
                    batch_count = 0
    if batch_count and on_batch:
        on_batch(batch_count)


def _increment_quality(quality: object | None, name: str) -> None:
    """Increment a mutable quality counter when one is available."""
    if quality is None or not hasattr(quality, name):
        return
    setattr(quality, name, getattr(quality, name) + 1)


def _increment_reason(quality: object | None, reason: str) -> None:
    """Increment a ReadQuality reason bucket."""
    if quality is None or not hasattr(quality, "reason_counts"):
        return
    quality.reason_counts[reason] += 1


def _classify_validation_error(message: str) -> str:
    """Map validation text to the stable measurement quality taxonomy."""
    lowered = message.lower()
    if "schema" in lowered:
        return "schema"
    if "required" in lowered:
        return "required_field"
    if "sequence" in lowered:
        return "sequence"
    if "feature_state_version" in lowered or "state version" in lowered:
        return "state_version"
    if "terminal" in lowered or "action_phase" in lowered:
        return "terminal"
    if "time" in lowered or "monotonic" in lowered:
        return "time"
    if "payload" in lowered:
        return "schema"
    return "schema"


def _declares_gap(event: EventEnvelope, expected: int) -> bool:
    """Return whether a recording_gap event explicitly covers a gap."""
    if event.event_type != "recording_gap":
        return False
    payload = event.payload or {}
    return (
        int(payload.get("gap_start_sequence_no", -1))
        <= expected
        <= int(payload.get("gap_end_sequence_no", -1))
    )
